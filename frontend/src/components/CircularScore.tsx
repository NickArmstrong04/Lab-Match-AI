import React from 'react';

interface CircularScoreProps {
  score: number; // 0 to 100
  size?: number; // width/height in px
  strokeWidth?: number;
  showText?: boolean;
}

export const CircularScore: React.FC<CircularScoreProps> = ({
  score,
  size = 120,
  strokeWidth = 10,
  showText = true,
}) => {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const strokeDashoffset = circumference - (score / 100) * circumference;

  // Color selection based on score threshold
  const getColor = (s: number) => {
    if (s >= 90) return 'stroke-teal-400';
    if (s >= 75) return 'stroke-purple-400';
    if (s >= 50) return 'stroke-yellow-400';
    return 'stroke-rose-400';
  };

  const getGlowColor = (s: number) => {
    if (s >= 90) return 'rgba(45, 212, 191, 0.4)';
    if (s >= 75) return 'rgba(168, 85, 247, 0.4)';
    if (s >= 50) return 'rgba(234, 179, 8, 0.4)';
    return 'rgba(244, 63, 94, 0.4)';
  };

  const colorClass = getColor(score);
  const glowStyle = {
    filter: `drop-shadow(0px 0px 6px ${getGlowColor(score)})`,
  };

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
      <svg className="transform -rotate-90" width={size} height={size}>
        {/* Background Circle */}
        <circle
          className="stroke-[rgba(255,255,255,0.05)] fill-transparent"
          strokeWidth={strokeWidth}
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
        {/* Foreground Circle */}
        <circle
          className={`fill-transparent transition-all duration-1000 cubic-bezier(0.4, 0, 0.2, 1) ${colorClass}`}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          style={glowStyle}
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
      </svg>

      {showText && (
        <div className="absolute flex flex-col items-center justify-center">
          <span className="font-extrabold tracking-tight text-white font-outfit" style={{ fontSize: size * 0.24 }}>
            {score}%
          </span>
          <span className="text-[10px] tracking-wider text-slate-400 uppercase font-semibold">Match</span>
        </div>
      )}
    </div>
  );
};

export default CircularScore;
