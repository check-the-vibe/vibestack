'use strict';

if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/service-worker.js', { scope: '/' }).catch((error) => {
    console.warn('VibeStack service worker registration failed:', error);
  });
}

// Fresh workspaces complete password and component onboarding before the
// launcher becomes their stable entrypoint. A completed explicit CLI skip is
// respected, which keeps unattended acceptance and recovery workflows usable.
fetch('/setup/api/state', { cache: 'no-store', credentials: 'same-origin' })
  .then((response) => (response.ok ? response.json() : null))
  .then((data) => {
    if (
      data?.state_valid === true &&
      (data.state?.completed !== true || data.authentication?.password_configured !== true)
    ) {
      // Force the wizard for this navigation so the setup server cannot race
      // a state change between this check and the following page request.
      window.location.replace('/setup/?force=1');
    }
  })
  .catch(() => {
    // The launcher remains useful for recovery if setup is temporarily down.
  });
