// Node's strict ESM resolver rejects extensionless / directory specifiers that
// bundlers (esbuild, vite) accept. @empirica/tajriba ships such imports
// (e.g. "cross-fetch/polyfill"). Retry with the usual fallbacks so the headless
// bots can load the same packages the real client bundles.
export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (err) {
    if (err.code !== "ERR_UNSUPPORTED_DIR_IMPORT" && err.code !== "ERR_MODULE_NOT_FOUND") throw err;
    if (specifier === "cross-fetch/polyfill") {
      return nextResolve("cross-fetch/dist/node-polyfill.js", context);
    }
    for (const suffix of [".js", "/index.js", ".mjs", ".cjs"]) {
      try { return await nextResolve(specifier + suffix, context); } catch (_) { /* try next */ }
    }
    throw err;
  }
}
