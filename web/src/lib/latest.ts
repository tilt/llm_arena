// Overlapping loads where only the newest answer may land: a slow, older response must not overwrite a newer one
// (e.g. clicking Rename on one run, then on another before the first run has loaded).

/** Returns `begin`: each call starts a load and returns a check that stays true until a newer load begins. */
export function newest(): () => () => boolean {
  let latest = 0;
  return () => {
    const mine = ++latest;
    return () => mine === latest;
  };
}
