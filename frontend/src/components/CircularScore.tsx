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

  const getColor = (s: number) => {
    if (s >= 90) return 'stroke-teal-700';
    if (s >= 75) return 'stroke-slate-600';
    if (s >= 50) return 'stroke-amber-600';
    return 'stroke-rose-600';
  };

  const colorClass = getColor(score);

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
      <svg className="transform -rotate-90" width={size} height={size}>
        <circle
          className="stroke-stone-200 fill-transparent"
          strokeWidth={strokeWidth}
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
        <circle
          className={`fill-transparent transition-all duration-1000 cubic-bezier(0.4, 0, 0.2, 1) ${colorClass}`}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
      </svg>

      {showText && (
        <div className="absolute flex flex-col items-center justify-center">
          <span className="font-semibold tracking-tight text-stone-900 font-outfit" style={{ fontSize: size * 0.24 }}>
            {score}%
          </span>
          <span className="text-[10px] tracking-wider text-stone-500 uppercase font-medium">Match</span>
        </div>
      )}
    </div>
  );
};

export default CircularScore;
