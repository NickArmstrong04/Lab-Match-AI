import React from 'react';
import Onboarding from './Onboarding';

interface GetStartedProps {
  onComplete: (data: {
    resumeName: string;
    researchInterests: string;
    matches: any[];
    studentId?: string;
    studentName?: string;
    location?: string;
    email?: string;
    isAuthenticated?: boolean;
  }) => void;
  onHome: () => void;
}

export const GetStarted: React.FC<GetStartedProps> = ({ onComplete, onHome }) => {
  return (
    <div className="landing-shell">
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
