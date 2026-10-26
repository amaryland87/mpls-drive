// [Mpls] How high the street is at (x, z) for something now at height y: Slop New York's modules assume Manhattan's
// flat ground at y = 0; Minneapolis has hills and bridges. mpls-city.js sets `at` once the ground is loaded.
const ground = { at: (x, z, y) => 0 };

export { ground };
