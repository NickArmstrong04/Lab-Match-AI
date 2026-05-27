import React from 'react';

interface LandingTopBarProps {
  onHome?: () => void;
}

export const LandingTopBar: React.FC<LandingTopBarProps> = ({ onHome }) => {
  return (
    <header className="landing-top-bar">
      <button
        type="button"
        className="landing-top-bar-brand"
        onClick={onHome}
        aria-label="Back to home"
      >
        <img src="/labmatch-icon.png" alt="" width={28} height={28} className="landing-top-bar-icon" />
        <span>LabMatch AI</span>
      </button>
    </header>
  );
};

export default LandingTopBar;
