# coding=utf-8
from flask import Flask, request, redirect, session
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
import psycopg2
import urlparse
import googlemaps

SECRET_KEY = 'a secret key'
app = Flask(__name__)
app.config.from_object(__name__)

'''
# CONNECTING TO POSTGRES
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

    body = request.values.get('Body')
    print 'User message: "%s" (greeted: %r, located: %r)' % (body, greeted, located)

    # If first time user, send greeting and instructions
    if not greeted:
        m = "Hi! I'm the Boston Bench Buddy. I'll find a place to sit. Where are you?"
        session["greeted"] = True
        print "Greeting user ..."

    # Check user response
    elif not located:

        # Get text contents
        if "boston" not in body.lower():
            body = "%s Boston" % (body)

        # Check to see if user response is a place on Google Maps
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
            print "Found user at %s -- https://www.google.com/maps/search/?api=1&query=%f,%f" % (r['results'][0]['formatted_address'],lat,lon)

            # Make query to database
            query = "SELECT id, street, park, lon, lat FROM benches WHERE ST_DWithin(st_setsrid(st_makepoint(%(lon_)s,%(lat_)s),4326), geom, .004) ORDER BY geom <-> st_setsrid(st_makepoint(%(lon_)s,%(lat_)s),4326) LIMIT 100;"
            cursor.execute(query, {"lon_":lon, "lat_":lat})

            # If there are no benches nearby
            if cursor.rowcount == 0:
                m = "Hmm ... I couldn't find any benches near you. Try another place?"
                print "Could not find any benches ..."

            # If there are benches
            else:
                # Retrieve data from database query results
                benches = []
                for id_, street_, park_, lon_, lat_ in cursor:
                    benches.append({"id": id_,"street": street_, "park": park_, "lon":lon_, "lat":lat_})

                # Get Google Maps walking distance matrix for query results
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

                # Add descriptions of landmarks and identifiers, if applicable
                if bench["street"] != -1:
                    query = "SELECT name, type FROM streets WHERE id = " + str(bench["street"])
                    cursor.execute(query)
                    street = cursor.fetchone()

                    bench["street_name"] = street[0]
                    bench["street_type"] = street[1]

                    m += " along %s" % (bench["street_name"].title())
                    m += " %s" % (bench["street_type"].title()) if bench["street_type"] != "" else ""

                if bench["park"] != 0:
                    query = "SELECT name FROM parks WHERE id = " + str(bench["park"])
                    cursor.execute(query)
                    park = cursor.fetchone()

                    bench["park_name"] = park[0]

                    m += " in %s" % (bench["park_name"])

                # Add distance to bench
                m += " about %i ft and %s away!" % (bench["distance"], bench["duration"])

                print "Found nearest bench ..."
                '''
                # Send bench location to user
                resp = MessagingResponse()
                resp.message(m)

                # Construct follow-up message
                m = "Would you like to find another bench? Text 'Y' to start over."
                '''
    elif greeted and located and "Y" not in body:
        m = "We've got you a bench! Text 'Y' to start over!"
        print "Asking if they want to start over ..."

    elif "Y" in body:
        # session["greeted"] = False
        session["located"] = False
        m = "Okay! Where are you?"
        print "Starting session over ..."

    resp = MessagingResponse()
    resp.message(m)
    return str(resp)

if __name__ == '__main__':
    app.run(debug=True)
