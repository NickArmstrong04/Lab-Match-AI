import React from 'react';

export type CoverNavigate = 'get_started' | 'sign_in' | 'explore';

interface CoverProps {
  onNavigate: (target: CoverNavigate) => void;
}

/** Antigravity-inspired landing: large headline, pill CTAs. */
export const Cover: React.FC<CoverProps> = ({ onNavigate }) => {

  return (
    <div className="cover-page animate-fade-in">
      <div className="cover-content">
        <div className="cover-brand">
          <img
            src="/labmatch-icon.png"
            alt=""
            width={28}
            height={28}
            className="cover-brand-icon"
          />
          <span className="cover-brand-name">LabMatch AI</span>
        </div>

        <h1 className="cover-headline">
          <span>Build your research profile</span>
          <span>with funded NIH &amp; NSF labs</span>
        </h1>

        <div className="cover-cta-row">
          <button
            type="button"
            className="cover-pill cover-pill--primary"
            onClick={() => onNavigate('get_started')}
          >
            Get started
          </button>
          <button
            type="button"
            className="cover-pill cover-pill--secondary"
            onClick={() => onNavigate('explore')}
          >
            Explore use cases
          </button>
        </div>
      </div>
    </div>
  );
};

export default Cover;
