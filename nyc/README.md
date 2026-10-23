# Slop New York, in Minneapolis

The modules in this folder come from [Slop New York](https://github.com/mrdoob/slop-newyork) by Mr.doob (MIT, see
LICENSE), copied unchanged from commit `12593c9` unless noted:

- `lighting.js`, `post-processing.js`, `trees.js`, `actor-models.js`, `pedestrians.js`, `vehicle-lights.js`,
  `audio-synthesis.js`, `audio-events.js`: unchanged.
- `tsl-materials.js`: unchanged but for one marked `[Mpls Drive]` change in `createTreeMaterial` (leaf alpha scaled
  with the mip level, since three.js r186's WebGPU renderer doesn't upload the leaf atlas's own mip levels), and
  `evaluateApartmentInterior` added to its exports for Mpls Drive's facades.
- `city-config.js`: a stand-in for NYC's Manhattan geography (see the file).
- `audio.js`: Mpls Drive's own sound mixer, cut down from NYC's `audio-system.js`.
