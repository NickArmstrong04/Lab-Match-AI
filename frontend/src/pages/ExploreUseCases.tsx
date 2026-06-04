import React, { useEffect, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import { Database, ScanSearch, Mail, GraduationCap, BookOpen } from 'lucide-react';
import { trackEvent } from '../utils/analytics';

export type UseCaseId =
  | 'grant_alignment'
  | 'cv_synthesis'
  | 'outreach'
  | 'undergraduate'
  | 'graduate';

interface UseCase {
  id: UseCaseId;
  label: string;
  icon: LucideIcon;
  title: string;
  description: string;
}

const USE_CASES: UseCase[] = [
  {
    id: 'grant_alignment',
    label: 'Grant alignment',
    icon: Database,
    title: 'Grant alignment',
    description:
      'Surface actively funded NIH and NSF labs that overlap with your stated interests and parsed background—not stale job boards or generic listings.',
  },
  {
    id: 'cv_synthesis',
    label: 'CV synthesis',
    icon: ScanSearch,
    title: 'CV-aware profile synthesis',
    description:
      'Upload a PDF resume and our parser extracts publications, methods, and skills to power semantic matching against real award abstracts.',
  },
  {
    id: 'outreach',
    label: 'Outreach',
    icon: Mail,
    title: 'From match to outreach',
    description:
      'Review ranked lab fits, save your pipeline, and draft tailored cold emails grounded in both your narrative and each PI’s funded project.',
  },
  {
    id: 'undergraduate',
    label: 'Undergraduate',
    icon: GraduationCap,
    title: 'Undergraduate',
    description:
      'Build a research profile from coursework and early lab experience, then discover funded labs where your interests align with active federal awards.',
  },
  {
    id: 'graduate',
    label: 'Graduate',
    icon: BookOpen,
    title: 'Graduate',
    description:
      'Compare PhD and masters programs against live NIH and NSF portfolios so your application narrative matches labs that are hiring and funded today.',
  },
];

interface ExploreUseCasesProps {
  onGetStarted: () => void;
  onHome: () => void;
}

export const ExploreUseCases: React.FC<ExploreUseCasesProps> = ({ onGetStarted, onHome }) => {
  const [activeId, setActiveId] = useState<UseCaseId>('grant_alignment');
  const active = USE_CASES.find((u) => u.id === activeId) ?? USE_CASES[0];
  const ActiveIcon = active.icon;

  useEffect(() => {
    trackEvent('view_page', 'explore', 'page_view');
  }, []);

  const handleSelect = (id: UseCaseId) => {
    setActiveId(id);
    trackEvent('explore_use_case_selected', 'explore', 'action', { use_case_id: id });
  };

  return (
    <div className="explore-page animate-fade-in">
      <div className="explore-body">
        <div className="explore-back-home-wrap w-full px-4 sm:px-6">
          <div className="onboarding-back-home-row">
            <button type="button" onClick={onHome} className="onboarding-back-home">
              ← Back to home
            </button>
          </div>
        </div>

        <div className="explore-layout">
        <nav className="explore-sidebar" aria-label="Use cases">
          {USE_CASES.map(({ id, label, icon: Icon }) => {
            const isActive = id === activeId;
            return (
              <button
                key={id}
                type="button"
                className={`explore-sidebar-pill${isActive ? ' is-active' : ''}`}
                onClick={() => handleSelect(id)}
                aria-current={isActive ? 'true' : undefined}
              >
                <Icon className="explore-sidebar-pill-icon" strokeWidth={1.75} aria-hidden />
                <span>{label}</span>
              </button>
            );
          })}
        </nav>

        <div className="explore-main">
          <div className="explore-main-icon" aria-hidden>
            <ActiveIcon strokeWidth={1.5} />
          </div>
          <h1 className="explore-main-title">{active.title}</h1>
          <p className="explore-main-description">{active.description}</p>
          <button
            type="button"
            className="cover-pill cover-pill--primary explore-main-cta"
            onClick={() => {
              trackEvent('explore_get_started', 'explore', 'action', { use_case_id: activeId });
              onGetStarted();
            }}
          >
            Get started
          </button>
        </div>
        </div>
      </div>
    </div>
  );
};

export default ExploreUseCases;
