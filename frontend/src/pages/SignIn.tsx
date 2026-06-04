import React from 'react';
import Onboarding from './Onboarding';

interface SignInProps {
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
