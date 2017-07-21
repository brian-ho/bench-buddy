# coding=utf-8
from flask import Flask, request, redirect, session
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
import psycopg2
import urlparse
import googlemaps
import math
import json
import datetime

SECRET_KEY = 'a secret key'
app = Flask(__name__)
app.config.from_object(__name__)

# CONNECTING TO POSTGRES

'''
conn_string = "host='localhost' dbname='bench_buddy' user='brianho' password=''"
print "Connecting to database\n	-> %s" % (conn_string)
# get a connection, if a connect cannot be made an exception will be raised here
conn = psycopg2.connect(conn_string)
'''
urlparse.uses_netloc.append("postgres")
url = urlparse.urlparse(os.environ["DATABASE_URL"])

conn = psycopg2.connect(
    database=url.path[1:],
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port
)

# conn.cursor will return a cursor object, you can use this cursor to perform queries
cursor = conn.cursor()
print "Connected!\n"

# SETUP GOOGLE MAPS API CLIENT
gmaps = googlemaps.Client(key=os.environ["GOOGLE_MAPS_KEY"])

# ROUTE FOR ALL INCOMING SMS
@app.route('/', methods=['GET', 'POST'])
def test_reponse():

    # Track the conversation
    greeted = session.get("greeted", False)
    located = session.get("located", False)
    found = session.get("found", False)
    bench_id = session.get("bench", -1)
    named = session.get("named", False)
    lat = session.get("lat", -9999)
    lon = session.get("lon", -9999)

    body = request.values.get('Body').encode('utf-8')
    print 'User message: "%s" (greeted: %r, located: %r, bench_id: %r, named: %r, lat: %s, lon: %s)' % (body, greeted, located, bench_id, named, lat, lon)

    # If first time user, send greeting and instructions
    if not greeted:
        m = "Hi! I'm the Boston Bench Buddy. I'll find you a place to sit. Where are you?"
        session["greeted"] = True
        print "Greeting user ..."

    # Escape commands
    elif body.lower()=="restart" or body.lower() == "n":
        # session["greeted"] = False
        session["located"] = False
        session["named"] = False
        session.get("found", False)
        session["bench"] = -1
        session.get("lat", -9999)
        session.get("lon", -9999)
        m = "Okay! I'm the Boston Bench Buddy. I'll find you a place to sit. Where are you?"
        print "Starting session over ..."

    # Check user response
    elif not located:

        # Get text contents
        if "boston" not in body.lower() and any(c.isalpha() for c in body.lower()):
            body = "%s Boston" % (body)

        # Check to see if user response is a place on Google Maps
        print "Finding user ..."
        r = gmaps.places(body)

        # Can't find user response as a location
        if r['status'] == 'ZERO_RESULTS':
            m = "Hmmm ... I couldn't find your location. Where are you?"
            print "Could not find user location..."

        # Found user location
        elif r['status'] == 'OK':
            session["located"] = True

            # Parse first Google Maps result
            user = r['results'][0]['geometry']['location']
            lon, lat = user['lng'], user['lat']
            session['lon'], session['lat'] = lon, lat
            map_url = short_url ("https://www.google.com/maps/search/?api=1&query=%f,%f" % (lat,lon))
            print "Found user at %s -- %s" % (r['results'][0]['formatted_address'], map_url)

            # Make query to database
            query = "SELECT id, street, park, lon, lat, name FROM benches WHERE ST_DWithin(st_setsrid(st_makepoint(%(lon_)s,%(lat_)s),4326), geom, .004) ORDER BY geom <-> st_setsrid(st_makepoint(%(lon_)s,%(lat_)s),4326) LIMIT 25;"
            cursor.execute(query, {"lon_":lon, "lat_":lat})
            print "Querying database for nearby benches ..."

            # If there are no benches nearby
            if cursor.rowcount == 0:
                m = "Hmm ... I couldn't find any benches near you. Want a bench here? Text 'Y', or 'restart' to try another place!"
                print "Could not find any benches ..."

            # If there are benches
            else:
                print "Found some benches ..."
                session.get("found", True)
                # Retrieve data from database query results
                benches = []
                for id_, street_, park_, lon_, lat_, name_ in cursor:
                    benches.append({"id": id_,"street": street_, "park": park_, "lon":lon_, "lat":lat_, "name":name_})

                # Get Google Maps walking distance matrix for query results
                print "Asking Google for distances ..."
                r = gmaps.distance_matrix(origins="%f,%f" % (lat,lon), destinations=[(bench["lat"],bench["lon"]) for bench in benches], mode="walking", units="imperial")

                # Find the nearest by walking
                min_dist = 9999
                min_index = -1
                for i, bench in enumerate(benches):
                    bench["distance"] = int(r['rows'][0]['elements'][i]['distance']['value']*3.28084)
                    bench["duration"] = r['rows'][0]['elements'][i]['duration']['text']

                    if bench["distance"] < min_dist:
                        min_dist = bench["distance"]
                        min_index = i

                # Construct message intro
                m = "Closest bench is"
                bench = benches[min_index]

                if bench["name"]:
                    m += " %s" % (bench["name"])

                # Add descriptions of landmarks and identifiers, if applicable
                # Streets
                if bench["street"] != -1:
                    query = "SELECT name, type FROM streets WHERE id = %i" % (bench["street"])
                    cursor.execute(query)
                    street = cursor.fetchone()

                    bench["street_name"] = street[0]
                    bench["street_type"] = street[1]

                    m += " along %s" % (bench["street_name"].title())
                    if bench["street_type"] != "":
                        m += " %s" % (bench["street_type"].title())

                # Parks
                if bench["park"] != 0:
                    query = "SELECT name FROM parks WHERE id = %i" % (bench["park"])
                    cursor.execute(query)
                    park = cursor.fetchone()

                    bench["park_name"] = park[0]

                    m += " in %s" % (bench["park_name"])

                m += " ... about %i ft and %s away to the %s!" % (bench["distance"], bench["duration"], ordinal(lon, bench["lon"], lat, bench["lat"]))

                if not bench["name"]:
                    m += " \n\nWant to name this bench? Text a name, or text 'restart' or 'N' to start over."
                else:
                    m += "\n\nText 'restart' or to find another!"

                # Add distance to bench
                map_url = short_url("\nhttps://www.google.com/maps/dir/?api=1&origin=%s,%s&destination=%s,%s&travelmode=walking" % (lat, lon, bench["lat"], bench["lon"]))
                m += "\n%s" % (map_url)

                session["bench"] = bench["id"]
                print "Found nearest bench -- %s" % (map_url)

    elif greeted and located and not found and 'y' in body.lower():
        query = "INSERT INTO desired (lat, lon, datetime) VALUES (%(lat_)s, %(lon_)s, %(time_)s);"
        cursor.execute(query, {'lat_': session['lat'], 'lon_': session['lon'], 'time_': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')})
        m = "Okay! I've saved that location. Text 'restart' to try and find another."
        conn.commit()

    elif greeted and located and named and "restart" not in body.lower():
        m = "I've already found you a bench. Text 'restart' to find another!"
        print "Asking if they want to start over ..."

    elif greeted and located and "restart" not in body.lower():
        try:
            body.decode('ascii')
        except UnicodeDecodeError:
            m = "Simple names only, please! Try another name?"
            print "Name not ASCII. Asking for another ..."
        else:
            if len(body) < 32:
                query = "UPDATE benches SET name = %(name)s WHERE id = %(id)s;"
                cursor.execute(query, ({"name":body.upper(), "id":session["bench"]}))

                m = "Okay, that bench will be called %s!\nText 'restart' to find another! " % (body.upper())
                session["named"] = True
                print "Named bench %s" % (body.upper())
            else:
                m = "That name is too long. Try another name?"
                print "Name was too long. Asking for another ..."

    resp = MessagingResponse()
    resp.message(m)
    return str(resp)

# HELPER FUNCTIONS
# Gets cardinal direction
def ordinal(x1, x2, y1, y2):
    dirs = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
    bearing = (90-math.degrees(math.atan2((y2-y1),(x2-x1))))%360
    ix = int(math.floor(((bearing + 22.5)%360)/45))
    return dirs[ix]

# Gets a short url
def short_url(url):
    post_url = 'https://www.googleapis.com/urlshortener/v1/url?key=%s' % (os.environ['GOOGLE_SHORTENER_KEY'])
    params = json.dumps({'longUrl': url})
    r = requests.post(post_url,params,headers={'Content-Type': 'application/json'})
    return r.json()['id']

if __name__ == '__main__':
    app.run(debug=True)
