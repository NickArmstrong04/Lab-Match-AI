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
  const glowClasses = {
    teal: 'border-[rgba(45,212,191,0.2)] shadow-[0_8px_32px_0_rgba(45,212,191,0.08)] hover:border-[rgba(45,212,191,0.35)]',
    purple: 'border-[rgba(168,85,247,0.2)] shadow-[0_8px_32px_0_rgba(168,85,247,0.08)] hover:border-[rgba(168,85,247,0.35)]',
    emerald: 'border-[rgba(16,185,129,0.2)] shadow-[0_8px_32px_0_rgba(16,185,129,0.08)] hover:border-[rgba(16,185,129,0.35)]',
    rose: 'border-[rgba(244,63,94,0.2)] shadow-[0_8px_32px_0_rgba(244,63,94,0.08)] hover:border-[rgba(244,63,94,0.35)]',
    none: 'border-[rgba(255,255,255,0.08)] shadow-[0_8px_32px_0_rgba(0,0,0,0.37)]',
  };

  return (
    <div
      onClick={onClick}
      className={`
        glass-panel 
        rounded-2xl 
        p-6 
        transition-all 
        duration-300 
        ${glowClasses[glowColor]} 
        ${onClick ? 'cursor-pointer hover:bg-[rgba(13,22,42,0.6)]' : ''} 
        ${className}
      `}
    >
      {children}
    </div>
  );
};

export default GlassCard;
