// Backwards-compatible entrypoint: delegate to split component files.
export { default } from './components/widget';
export { GeoGebraWidget } from './components/lumino';

// Note: the original monolithic implementation was moved to
// `src/components/GeoGebraApplet.tsx` and `src/components/lumino.tsx`.
// For historical reference, see the `restore-v1.3.4` branch.
