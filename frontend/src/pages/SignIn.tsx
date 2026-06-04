import React from 'react';
import Onboarding from './Onboarding';

interface SignInProps {
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

export const SignIn: React.FC<SignInProps> = ({ onComplete, onHome }) => {
  return (
    <div className="landing-shell">
      <Onboarding
        entry="returning"
        showHero
        lockReturning
        onComplete={onComplete}
        onBackToCover={onHome}
      />
    </div>
  );
};

export default SignIn;
