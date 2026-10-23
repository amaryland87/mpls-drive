// Stand-in for Slop New York's city-config.js, which holds Manhattan's geography: the copied modules here
// (tsl-materials.js) import a few of its names. In Minneapolis there is no Central Park to open the sky over and no
// harbour, so the "park" covers the whole map (no street-canyon darkening of the sky light) and the harbour water
// (createWaterMaterial, which Mpls Drive doesn't use) has nothing to work from.
const CENTRAL_PARK_BOUNDS = { minX: -1e6, maxX: 1e6, minZ: -1e6, maxZ: 1e6 };
const ISLAND_BOUNDS = null;
const NJ_SHORELINE_POLYGON = [];
const LONG_ISLAND_POLYGONS = [];
const streetZ = () => 0;
const getIslandBoundsAtZ = () => ({ westX: -1e6, eastX: 1e6 });

export { CENTRAL_PARK_BOUNDS, ISLAND_BOUNDS, NJ_SHORELINE_POLYGON, LONG_ISLAND_POLYGONS, streetZ, getIslandBoundsAtZ };
