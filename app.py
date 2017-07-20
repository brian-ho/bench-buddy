from flask import Flask, request, redirect
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
import psycopg2
import urlparse
import googlemaps

app = Flask(__name__)

# CONNECTING TO POSTGRES
'''
conn_string = "host='localhost' dbname='bench_buddy' user='brianho' password=''"
# print the connection string we will use to connect
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

# DEFAULT ROUTE FOR INCOMING SMS
@app.route('/', methods=['GET', 'POST'])
def test_reponse():

    # Get text contents
    body = request.values.get('Body')
    print 'Received request: ' + body

    # Check to see if it is a place
    r = gmaps.places(body)
    # Check to see if the message is a place
    if r['status'] == 'OK':
        location = r['results'][0]['geometry']['location']
        lat = str(location['lat'])
        lon = str(location['lng'])

    # Make a query
    query = "SELECT id, street, park, ST_Distance_Sphere(geom, st_setsrid(st_makepoint(%(lon_)s,%(lat_)s),4326)) FROM benches ORDER BY geom <-> st_setsrid(st_makepoint(%(lon_)s,%(lat_)s),4326) LIMIT 3;"
    print query
    cursor.execute(query, {"lon_":lon, "lat_":lat})

    # Retrieve data from query result
    benches = []
    for id_, street_, park_, dist_ in cursor:
        benches.append({"id": id_, "dist": dist_, "street": street_, "park": park_})

    # Construct message
    message = "Nearby benches: \n"
    for record in benches:
        message += "Bench"

        if  record["street"] != -1:
            query = "SELECT name, type FROM streets WHERE id = " + str(record["street"])
            cursor.execute(query)
            street = cursor.fetchone()

            record["street_name"] = street[0]
            record["street_type"] = street[1]

            message += " on " + record["street_name"] + " " + record["street_type"]

        if record["park"] != 0:
            query = "SELECT name FROM parks WHERE id = " + str(record["park"])
            cursor.execute(query)
            park = cursor.fetchone()

            record["park_name"] = park[0]

            message += " in " + record["park_name"]

        message += " about " + str(int(record["dist"])) + " meters away.\n"

    resp = MessagingResponse()
    resp.message(message)

    return str(resp)

if __name__ == '__main__':
    app.run(debug=True)
