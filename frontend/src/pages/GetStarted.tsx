import React from 'react';
import LandingTopBar from '../components/LandingTopBar';
import Onboarding from './Onboarding';

interface GetStartedProps {
  onComplete: (data: {
    resumeName: string;
    researchInterests: string;
    matches: unknown[];
    studentId?: string;
    studentName?: string;
    location?: string;
  }) => void;
  onHome: () => void;
}

export const GetStarted: React.FC<GetStartedProps> = ({ onComplete, onHome }) => {
  return (
    <div className="landing-shell">
      <LandingTopBar onHome={onHome} />
      <Onboarding
        entry="new"
        showHero
        lockNewProfile
        onComplete={onComplete}
        onBackToCover={onHome}
      />
    </div>
  );
};

export default GetStarted;
