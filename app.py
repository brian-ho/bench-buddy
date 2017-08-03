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

SECRET_KEY = '\xb4\xa2\xe4\x91.%u+\xa1\xe1\xcb\xc5\xb0\x87\x06;6>\xf1)\x06\xd8\xce\x88'
app = Flask(__name__)
app.config.from_object(__name__)


'''
# CONNECTING TO POSTGRES
conn_string = "host='localhost' dbname='bench-buddy' user='brianho' password=''"
print "Connecting to database\n	-> %s" % (conn_string)
# get a connection, if a connect cannot be made an exception will be raised here
conn = psycopg2.connect(conn_string)
'''
urlparse.uses_netloc.append("postgres")
url = urlparse.urlparse(os.environ["HEROKU_POSTGRESQL_YELLOW_URL"])

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

zipcodes = ['02108', '02109', '02110', '02111', '02113', '02114', '02115', '02116', '02118', '02119', '02120',
 '02121', '02122', '02124', '02125', '02126', '02127', '02128', '02129', '02130', '02131', '02132',
 '02134', '02135', '02136', '02151', '02152', '02163', '02199', '02203', '02210', '02215', '02467']

neighborhoods = ['Boston','Allston','Back Bay','Bay Village','Beacon Hill','Brighton','Charlestown','Chinatown',
'Leather District','Dorchester','East Boston','Fenway Kenmore','Hyde Park','Jamaica Plain','Mattapan',
'Mission Hill','North End','Roslindale','Roxbury','South Boston','South End','West End','West Roxbury']

days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

# ROUTE FOR ALL INCOMING SMS
@app.route('/', methods=['GET', 'POST'])
def test_reponse():

    # Track the conversation
    greeted = session.get("greeted", False)
    restroom_mode = session.get("restroom_mode", False)
    located = session.get("located", False)
    found = session.get("found", False)
    bench_id = session.get("bench", -1)
    named = session.get("named", False)
    lat = session.get("lat", -9999)
    lon = session.get("lon", -9999)

    # Switch the thing (object noun)
    thing = "bathroom" if restroom_mode else "bench"
    things = "bathrooms" if restroom_mode else "benches"

    # Get user text contents
    body = request.values.get('Body').encode('utf-8')
    print 'User message: "%s" (greeted: %r, restroom: %r, located: %r, found: %r, bench_id: %r, named: %r, lat: %s, lon: %s)' % (body,greeted, restroom_mode, located, found, bench_id, named, lat, lon)

    # If first time user, send greeting and instructions
    if not greeted:
        m = "Hi! I'm the Boston Bench Buddy. I'll find you a place to sit. Where are you?\n\n"
        m += "Or text 'bathroom' to find a place to go."

        session["greeted"] = True
        print "Greeting user ..."

    # Trigger for bathroom mode / restart
    elif  (body.lower()=="restart" and restroom_mode) or body.lower()=="restroom" or body.lower()=="toilet" or body.lower()=="bathroom":
        m = "Okay! I'm also the Boston Bathroom Buddy. I'll find you a place to go. Where are you?\n\n"
        m += "Or text 'bench' to find a place to sit."

        session["restroom_mode"] = True
        session["located"] = False
        session["named"] = False
        session["found"] = False
        session["bench"] = -1
        session["lat"] = -9999
        session["lon"] = -9999
        print "Starting over in restroom mode ..."

    # Trigger for bench mode / restart
    elif (body.lower()=="restart" and not restroom_mode) or body.lower() == "n" or body.lower() == "bench":
        m = "Okay! I'm the Boston Bench Buddy. I'll find you a place to sit. Where are you?\n\n"
        m += "Or text 'bathroom' to find a place to go."

        session["restroom_mode"] = False
        session["located"] = False
        session["named"] = False
        session["found"] = False
        session["bench"] = -1
        session["lat"] = -9999
        session["lon"] = -9999
        print "Starting over in bench mode ..."

    # If greeted, check user response
    elif not located:
        # Get contents of user text, adding 'Boston' for good measure
        if all(neighborhood not in body.lower() for neighborhood in neighborhoods) and any(c.isalpha() for c in body.lower()):
            body = "%s Boston" % (body)

        # Check to see if user response is a place on Google Maps
        print "Finding user ..."
        r = gmaps.places(body)

        # Can't find response as a location
        if r['status'] == 'ZERO_RESULTS':
            m = "Hmmm ... I couldn't find your location. Where are you?"

            print "Could not find user location..."

        # Found user location!
        elif r['status'] == 'OK':
            # Parse first Google Maps result
            user = r['results'][0]['geometry']['location']
            lon, lat = user['lng'], user['lat']
            map_url = short_url ("https://www.google.com/maps/search/?api=1&query=%f,%f" % (lat,lon))

            session['lon'], session['lat'] = lon, lat
            print "Found user at %s -- %s" % (r['results'][0]['formatted_address'], map_url)

            # If location is outside of Boston
            if all(zipcode not in r['results'][0]['formatted_address'].lower() for zipcode in zipcodes) and all(neighborhood.lower() not in r['results'][0]['formatted_address'].lower() for neighborhood in neighborhoods):
                m = "Sorry, I can only search for %s within the city of Boston! Try another place?" % things

            # If location is in Boston
            else:
                session["located"] = True
                # Make query to database within radius, where 0.001 degree is about 360 feet
                if not restroom_mode:
                    query = "SELECT id, street, park, lon, lat, name FROM benches WHERE ST_DWithin(st_setsrid(st_makepoint(%(lon_)s,%(lat_)s),4326), geom, .002) ORDER BY geom <-> st_setsrid(st_makepoint(%(lon_)s,%(lat_)s),4326) LIMIT 5;"
                    cursor.execute(query, {"lon_":lon, "lat_":lat})
                else:
                    today = days[datetime.datetime.today().weekday()]
                    query = "SELECT id, address, lon, lat, name, " + today
                    query += " FROM restrooms WHERE ST_DWithin(st_setsrid(st_makepoint(%(lon_)s,%(lat_)s),4326), geom, .0075) ORDER BY geom <-> st_setsrid(st_makepoint(%(lon_)s,%(lat_)s),4326);"
                    cursor.execute(query, {"lon_":lon, "lat_":lat})

                print "Querying database for nearby %s ..." % things

                # If there are no things nearby
                if cursor.rowcount == 0:
                    m = "Hmm ... I couldn't find any %s near you." % things
                    m+= "\n\nWant a %s here? Text 'Y', or 'restart' to try another place!" % thing
                    print "Could not find any %s ..." % things

                # If there are things!
                else:
                    session["found"] = True
                    print "Found some %s ..." % things

                    # Retrieve data from database query results
                    results = []
                    if not restroom_mode:
                        for id_, street_, park_, lon_, lat_, name_ in cursor:
                            results.append({"id": id_,"street": street_, "park": park_, "lon":lon_, "lat":lat_, "name":name_})
                    elif restroom_mode:
                        for id_, address_, lon_, lat_, name_, hours_ in cursor:
                            results.append({"id": id_,"address": address_, "lon":lon_, "lat":lat_, "name":name_, "hours":hours_})

                    # Get Google Maps walking distance matrix for query results
                    print "Asking Google for distances ..."
                    r = gmaps.distance_matrix(origins="%f,%f" % (lat,lon), destinations=[(result["lat"],result["lon"]) for result in results], mode="walking", units="imperial")

                    # Find the nearest thing by walking, using Google
                    best = 0
                    for i, result in enumerate(results):
                        result["distance"] = int(r['rows'][0]['elements'][i]['distance']['value']*3.28084)
                        result["duration"] = r['rows'][0]['elements'][i]['duration']['text']

                    # Sort results by walking distance
                    results = sorted(results, key=lambda k: k['distance'])
                    best_result = results[best]

                    # Make sure first result is open, or see if nothing is open
                    closed = False;
                    start = ""
                    end = ""
                    if restroom_mode:
                        # Get current time
                        time = datetime.datetime.now().time()
                        print "Checking if open ..."

                        # Loop over results in order until either one is open or all exhausted
                        while True:
                            best_result = results[best]
                            # If closed all day
                            if best_result["hours"] == "closed":
                                closed = True;
                                best += 1
                            # Check against saved start and end times
                            else:
                                start = datetime.datetime.strptime(best_result["hours"][:5],'%H:%M').time()
                                end = datetime.datetime.strptime(best_result["hours"][-5:],'%H:%M').time()
                                # If closed
                                if start > time and time > end:
                                    closed = True;
                                    best += 1
                                # If open
                                elif start < time and time < end:
                                    closed = False
                                    break
                            # If at the end of results
                            if best == len(results):
                                break

                    # Message if result is open
                    if not closed:
                        # Construct message intro
                        m = "Closest %s is" % thing

                        if best_result["name"]:
                            m += " %s" % best_result["name"]
                            session["named"] = True

                        # MESSAGE ADDITIONS FOR BENCHES
                        if not restroom_mode:
                            # Add descriptions of landmarks and identifiers, if applicable
                            # Streets
                            if best_result["street"] != -1:
                                query = "SELECT name, type FROM streets WHERE id = %i" % (best_result["street"])
                                cursor.execute(query)
                                street = cursor.fetchone()

                                best_result["street_name"] = street[0]
                                best_result["street_type"] = street[1]

                                m += " along %s" % (best_result["street_name"].title())
                                if best_result["street_type"] != "":
                                    m += " %s" % (best_result["street_type"].title())

                            # Parks
                            if best_result["park"] != 0:
                                query = "SELECT name FROM parks WHERE id = %i" % (best_result["park"])
                                cursor.execute(query)
                                park = cursor.fetchone()

                                best_result["park_name"] = park[0]

                                m += " in %s" % (best_result["park_name"])

                        # MESSAGE ADDITIONS FOR BATHROOMS
                        elif restroom_mode:
                            m += " at %s, open" % (best_result["address"])
                            if start == datetime.time(0, 0, 0) and end == datetime.time(23, 59, 00):
                                m += " 24 hours"
                            else:
                                m += " until %s" % (end.strftime("%-I:%M %p"))

                        # Message conclusion
                        m += " ... about %i ft and %s away to the %s!" % (best_result["distance"], best_result["duration"], ordinal(lon, best_result["lon"], lat, best_result["lat"]))

                        if not best_result["name"]:
                            m += "\n\nWant to name this bench? Text a name, or text 'restart' or 'N' to start over."
                        else:
                            m += "\n\nText 'restart' to find another!"

                        # Add map to message
                        map_url = short_url("\nhttps://www.google.com/maps/dir/?api=1&origin=%s,%s&destination=%s,%s&travelmode=walking" % (lat, lon, best_result["lat"], best_result["lon"]))
                        m += "\n%s" % (map_url)

                        if not restroom_mode:
                            session["bench"] = best_result["id"]
                        print "Found nearest %s -- %s" % (thing, map_url)

                    # Message if all results are closed
                    elif closed:
                        m = "Sorry, all nearby %s are closed." % thing
                        m+= "\n\nWant a %s open here? Text 'Y', or 'restart' to try another place!" % thing

                        print "Could not find any open %s ..." % things

    # Making a request
    elif greeted and located and not found and not named and 'y' == body.lower():
        query = "INSERT INTO desired (lat, lon, datetime, type) VALUES (%(lat_)s, %(lon_)s, %(time_)s, %(type_)s);"
        cursor.execute(query, {'lat_': session['lat'], 'lon_': session['lon'], 'time_': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z'), 'type_': thing})
        conn.commit()

        m = "Okay! I've saved that location for a %s. Text 'restart' to try and find another %s." % (thing, thing)

        session["found"] = True
        session["named"] = True
        print "Saving sugested location for a %s at %s, %s" % (thing, session['lat'], session['lon'])

    # If there are further messages after finding
    elif greeted and located and found and named and "restart" != body.lower():
        if "thanks" in body.lower() or "thank you" in body.lower():
            m = "You're welcome! Text 'restart' to find another %s!" % thing
        else:
            m = "I've already found you a %s. Text 'restart' to find another!" % thing
        print "Asking if they want to start over ..."

    # If submitting a name
    elif greeted and located and found and not named and "restart" != body.lower():
        # Check name for no unicode
        try:
            body.decode('ascii')
        except UnicodeDecodeError:
            m = "Simple names only, please! Try another name?"
            print "Name not ASCII. Asking for another ..."

        else:
            # Check for length
            if len(body) > 32:
                m = "That name is too long. Try another name?"
                print "Name was too long. Asking for another ..."
            # Check for odd characters
            elif not all(c.isalnum() or c.isspace() for c in body.lower()):
                m = "Letters and spaces only, please. Try another name?"
                print "Name not alphanum or spaces. Asking for another ..."
            # Update name in database
            else:
                query = "UPDATE benches SET name = %(name)s WHERE id = %(id)s;"
                cursor.execute(query, ({"name":body.upper(), "id":session["bench"]}))
                conn.commit()

                m = "Okay, that bench will be called %s!\nText 'restart' to find another! " % (body.upper())
                session["named"] = True
                print "Named bench %s" % (body.upper())

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
