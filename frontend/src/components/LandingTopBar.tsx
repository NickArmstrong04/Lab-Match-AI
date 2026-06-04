import React from 'react';

interface LandingTopBarProps {
  view: 'cover' | 'get_started' | 'sign_in' | 'explore';
  onHome?: () => void;
  onSignIn: () => void;
  onGetStarted: () => void;
}

export const LandingTopBar: React.FC<LandingTopBarProps> = ({
  view,
  onHome,
  onSignIn,
  onGetStarted,
}) => {
  const isCover = view === 'cover';
  const isSignInPage = view === 'sign_in';

  return (
    <header
      className={`landing-top-bar${isCover ? ' landing-top-bar--cover' : ''}`}
      aria-label="Site header"
    >
      {isCover ? (
        <span className="landing-top-bar-spacer" aria-hidden="true" />
      ) : (
        <button
          type="button"
          className="landing-top-bar-brand"
          onClick={onHome}
          aria-label="Back to home"
        >
          <img src="/labmatch-icon.png" alt="" width={28} height={28} className="landing-top-bar-icon" />
          <span>LabMatch AI</span>
        </button>
      )}

      <div className="landing-top-bar-actions" aria-label="Account">
        {isSignInPage ? (
          <button type="button" className="landing-top-bar-auth" onClick={onGetStarted}>
            Get started
          </button>
        ) : (
          <button type="button" className="landing-top-bar-auth" onClick={onSignIn}>
            Sign in
          </button>
        )}
      </div>
    </header>
  );
};

export default LandingTopBar;
