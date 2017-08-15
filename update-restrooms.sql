CREATE TABLE restrooms 
(id integer, name text, address text, monday text, tuesday text, wednesday text,
thursday text, friday text, saturday text, sunday text, lon double precision,
lat double precision);

\COPY restrooms FROM 'restrooms.csv' DELIMITER ',' CSV HEADER;

ALTER TABLE "restrooms" ADD COLUMN "geom" geometry;

UPDATE restrooms SET geom = ST_SetSRID(ST_MakePoint(lon,lat),4326);
