import React from 'react';

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  glowColor?: 'teal' | 'purple' | 'emerald' | 'rose' | 'none';
  onClick?: () => void;
}

export const GlassCard: React.FC<GlassCardProps> = ({
  children,
  className = '',
  glowColor = 'none',
  onClick,
}) => {
  const accentClasses = {
    teal: 'panel-card-accent-teal',
    purple: 'panel-card-accent-purple',
    emerald: 'panel-card-accent-emerald',
    rose: 'panel-card-accent-rose',
    none: '',
  };

  return (
    <div
      onClick={onClick}
      className={`
        panel-card
        p-6
        transition-all
        duration-300
        ${accentClasses[glowColor]}
        ${onClick ? 'cursor-pointer hover:border-stone-300 hover:shadow-md' : ''}
        ${className}
      `}
    >
      {children}
    </div>
  );
};

export default GlassCard;
