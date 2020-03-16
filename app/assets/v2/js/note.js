function RAFThrottle(f) {
  let throttledHandler;

  return function() {
    if (throttledHandler) {
      return;
    }

    throttledHandler = requestAnimationFrame(() => {
      f(...arguments);
      throttledHandler = undefined;
    });
  };
}
