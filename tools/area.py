"""The ground Mpls Drive covers, shared by fetch_osm.py and bake_tiles.py.

Game units are metres: x east, z south, centred on 44.966 N, 93.259 W (downtown).
The map runs a mile past Bde Maka Ska to the west and takes in Lake Harriet to the south.
"""
import math

LAT0, LON0 = 44.966, -93.259
MX = 111320 * math.cos(math.radians(LAT0))   # metres per degree of longitude
MY = 110574                                    # metres per degree of latitude

TILE = 1000                                    # one ground image and one data file per km square
X0, X1 = -7000, 4000
Z0, Z1 = -4000, 6000
