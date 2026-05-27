import React from 'react';

interface LandingSignInBarProps {
  view: 'cover' | 'get_started' | 'sign_in' | 'explore';
  onSignIn: () => void;
  onGetStarted: () => void;
}

/** Fixed top-right auth control — same position on cover and all landing routes. */
export const LandingSignInBar: React.FC<LandingSignInBarProps> = ({
  view,
  onSignIn,
  onGetStarted,
}) => {
  const isSignInPage = view === 'sign_in';

  return (
    <div className="landing-signin-fixed" aria-label="Account">
      {isSignInPage ? (
        <button type="button" className="cover-signin" onClick={onGetStarted}>
          Get started
        </button>
      ) : (
        <button type="button" className="cover-signin" onClick={onSignIn}>
          Sign in
        </button>
      )}
    </div>
  );
};

export default LandingSignInBar;
