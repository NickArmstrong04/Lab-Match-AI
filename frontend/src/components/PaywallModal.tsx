import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Check, X, Shield, CreditCard, HelpCircle } from 'lucide-react';
import GlassCard from './GlassCard';
import { trackEvent } from '../utils/analytics';

interface PaywallModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const getTodayDateString = () => {
  const dateObj = new Date();
  return `${dateObj.getFullYear()}-${String(dateObj.getMonth() + 1).padStart(2, '0')}-${String(dateObj.getDate()).padStart(2, '0')}`;
};

export const PaywallModal: React.FC<PaywallModalProps> = ({ isOpen, onClose }) => {
  const [variant, setVariant] = useState<'subscription' | 'lifetime'>('subscription');
  const [isUpgraded, setIsUpgraded] = useState(false);
  const [hasFeedbackToday, setHasFeedbackToday] = useState(false);

  useEffect(() => {
    if (!isOpen) return;

    // Reset feedback submission state on reopen
    setIsUpgraded(false);

    // Check if variant is already assigned, otherwise assign 50/50 randomly
    let activeVariant = localStorage.getItem('labmatch_ab_variant') as 'subscription' | 'lifetime' | null;
    if (!activeVariant) {
      activeVariant = Math.random() < 0.5 ? 'subscription' : 'lifetime';
      localStorage.setItem('labmatch_ab_variant', activeVariant);
    }
    setVariant(activeVariant);

    // Check if feedback was already provided today
    const todayStr = getTodayDateString();
    const storedFeedbackDate = localStorage.getItem('labmatch_feedback_date');
    const hasFeedback = storedFeedbackDate === todayStr;
    setHasFeedbackToday(hasFeedback);

    // Track modal view event
    trackEvent('paywall_view', 'dashboard', 'action', {
      variant: activeVariant,
      price: activeVariant === 'subscription' ? '$4.99/mo' : '$4.99 one-time',
      already_has_feedback: hasFeedback
    });
  }, [isOpen]);

  // What role="dialog" aria-modal="true" below promises. The overlay was portalled and
  // declared modal while focus stayed on the Save or Skip button behind it: Escape did
  // nothing, and since the portal is the last child of <body>, Tab walked through
  // Details, Draft outreach, the sidebar and the footer under the backdrop before it
  // reached the dialog (Enter on Draft outreach opened the composer beneath the
  // paywall). Same pattern as ProfileBasisPanel: focus the close button on open, Escape
  // in the capture phase so the Dashboard's own Escape handler (undo, leave inspect)
  // does not also run. Added here: Tab is kept inside the dialog, the page behind does
  // not scroll, and focus goes back to where it was. No copy or limit logic is touched.
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  // The latest close handler, so the listener below is bound once per opening and
  // still reports the variant that was assigned after it was bound.
  const closeRef = useRef<() => void>(() => {});
  useEffect(() => {
    if (!isOpen) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopImmediatePropagation();
        closeRef.current();
        return;
      }
      if (e.key !== 'Tab') return;
      const root = dialogRef.current;
      if (!root) return;
      const stops = Array.from(
        root.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, textarea, select'),
      );
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      const active = document.activeElement;
      if (!root.contains(active)) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      document.body.style.overflow = previousOverflow;
      // Only if it is still on the page: the card behind may have changed.
      if (previous && document.contains(previous)) previous.focus();
    };
  }, [isOpen]);

  const priceText = variant === 'subscription' ? '$4.99/month' : '$4.99 one-time';

  const handleFeedback = (answer: 'yes' | 'no') => {
    const todayStr = getTodayDateString();
    localStorage.setItem('labmatch_feedback_date', todayStr);
    localStorage.setItem('labmatch_pricing_feedback', answer);

    trackEvent('paywall_feedback', 'dashboard', 'action', {
      answer: answer,
      variant: variant,
      price: priceText
    });

    setIsUpgraded(true);
  };

  const handleClose = () => {
    trackEvent('paywall_close', 'dashboard', 'action', {
      variant: variant,
      price: priceText
    });
    onClose();
  };
  // In an effect: a ref is not written during render.
  useEffect(() => {
    closeRef.current = handleClose;
  });

  // After the last hook: hooks run in the same order whether or not it is open.
  if (!isOpen) return null;

  // Portalled to <body>, like the narrative editor and the profile panel. The
  // Dashboard's root keeps a transform from animate-fade-in, which makes it the
  // containing block for `fixed` children and a stacking context of its own: drawn
  // inside it, this overlay covered the dashboard instead of the viewport (at 1280 the
  // backdrop stopped short of the header and the footer) and its z-index could not rise
  // above the app header's z-40 (at 390 the header was painted over the modal's title).
  // z-[60]: above the header and above the toast slot, which is z-50 on <body> too.
  //
  // The overlay scrolls and the card is centred inside a min-h-full wrapper. Centred
  // directly in a fixed box, a card taller than the screen (it is about 900px at 360
  // wide) had its top and its close button cut off with no way to reach them.
  return createPortal(
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label="Daily swipe limit"
      className="fixed inset-0 z-[60] overflow-y-auto bg-stone-950/80 backdrop-blur-md animate-fade-in"
    >
      <div className="flex min-h-full items-center justify-center p-4">
      <GlassCard 
        className="relative w-full max-w-lg overflow-hidden flex flex-col p-8 bg-white border border-stone-200 text-stone-900 shadow-2xl rounded-3xl"
        glowColor="none"
      >
        {/* Close Button */}
        <button
          ref={closeButtonRef}
          onClick={handleClose}
          className="absolute top-4 right-4 p-2 rounded-full text-stone-400 hover:text-stone-700 hover:bg-stone-100 transition-colors cursor-pointer"
          aria-label="Close"
        >
          <X className="w-5 h-5" />
        </button>

        {hasFeedbackToday ? (
          <div className="space-y-6 py-4 text-center">
            {/* Warning/Limit Icon */}
            <div className="mx-auto w-16 h-16 rounded-full bg-amber-50 border border-amber-200 flex items-center justify-center">
              <Shield className="w-8 h-8 text-amber-600 animate-pulse" />
            </div>

            {/* Limit Message */}
            <div className="space-y-2">
              <h3 className="text-3xl font-extrabold font-outfit text-stone-900 tracking-tight">
                Daily Limit Reached (20/20)
              </h3>
              <p className="text-stone-600 text-sm max-w-sm mx-auto leading-relaxed">
                You've used all 20 of your unlocked swipes for today. Since we are currently in invite-only private beta, we limit daily swipes to manage compute load.
              </p>
              <p className="text-stone-500 text-xs max-w-xs mx-auto leading-relaxed pt-2">
                We've noted your pricing preference and marked your profile as an early adapter. We will email you the moment Stripe payments are activated!
              </p>
            </div>

            {/* Back to Dashboard Button */}
            <button
              onClick={onClose}
              className="w-full py-4 px-6 rounded-xl bg-[#1e3a4a] hover:bg-[#163040] text-white font-bold transition-all duration-200 cursor-pointer shadow-md hover:shadow-lg hover:shadow-[#1e3a4a]/10 text-center flex items-center justify-center gap-2 border-0"
            >
              Back to Dashboard
            </button>
          </div>
        ) : !isUpgraded ? (
          <div className="space-y-6">
            {/* Header Badge */}
            <div className="flex justify-center">
              <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold font-mono tracking-wider bg-stone-100 border border-stone-200 text-stone-700">
                LABMATCH PREMIUM
              </span>
            </div>

            {/* Title */}
            <div className="text-center space-y-2">
              <h3 className="text-3xl font-extrabold font-outfit text-stone-900 tracking-tight">
                Daily Swipe Limit Reached
              </h3>
              <p className="text-stone-500 text-sm max-w-sm mx-auto leading-relaxed">
                Aligning student vectors with federal NIH & NSF grants takes serious compute power. Give us feedback to unlock extra swipes today.
              </p>
            </div>

            {/* Core Features List */}
            <div className="space-y-3 bg-stone-50 border border-stone-200 rounded-2xl p-5 text-sm">
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-stone-100 border border-stone-200 flex items-center justify-center shrink-0 mt-0.5">
                  <Check className="w-3 h-3 text-stone-600" />
                </div>
                <div>
                  <strong className="text-stone-900 font-semibold">20 Swipes & Deck Restarts Today</strong>
                  <p className="text-stone-500 text-xs">Explore more NIH & NSF grant matches across the country.</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-stone-100 border border-stone-200 flex items-center justify-center shrink-0 mt-0.5">
                  <Check className="w-3 h-3 text-stone-600" />
                </div>
                <div>
                  <strong className="text-stone-900 font-semibold">Bespoke Cold Email Drafting</strong>
                  <p className="text-stone-500 text-xs">Generate unlimited high-converting outreach pitches tailored by Gemini.</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-stone-100 border border-stone-200 flex items-center justify-center shrink-0 mt-0.5">
                  <Check className="w-3 h-3 text-stone-600" />
                </div>
                <div>
                  <strong className="text-stone-900 font-semibold">Editable Pitch Composer</strong>
                  <p className="text-stone-500 text-xs">Refine each draft and copy it straight into your own email client.</p>
                </div>
              </div>
            </div>

            {/* Pricing Feedback Survey Box */}
            <div className="space-y-4 py-5 px-6 bg-stone-50 border border-stone-200 rounded-2xl">
              <div className="flex items-center gap-2 text-stone-700">
                <HelpCircle className="w-5 h-5 text-[#0d5c5c] shrink-0" />
                <span className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                  Quick feedback request
                </span>
              </div>
              <p className="text-stone-800 text-sm font-semibold leading-relaxed">
                {variant === 'subscription' 
                  ? "Would you subscribe at $4.99/month for this service?" 
                  : "Would you pay $4.99 one-time for this service?"}
              </p>
              
              <div className="flex gap-3">
                <button
                  onClick={() => handleFeedback('yes')}
                  className="flex-1 py-3.5 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-bold transition-all duration-200 cursor-pointer shadow-sm text-center flex items-center justify-center gap-1.5 border-0 hover:shadow-emerald-600/10 hover:shadow-md"
                >
                  Yes
                </button>
                <button
                  onClick={() => handleFeedback('no')}
                  className="flex-1 py-3.5 px-4 rounded-xl bg-stone-200 hover:bg-stone-300 text-stone-800 font-bold transition-all duration-200 cursor-pointer shadow-sm text-center flex items-center justify-center gap-1.5 border-0"
                >
                  No
                </button>
              </div>
              <span className="text-[11px] text-stone-500 block text-center mt-1">
                Answering unlocks <strong>20 swipes</strong> for today!
              </span>
            </div>

            {/* Close / Keep Free button */}
            <div className="space-y-3">
              <button
                onClick={handleClose}
                className="w-full py-3 px-6 rounded-xl bg-transparent border border-stone-200 hover:border-stone-300 text-stone-600 hover:text-stone-800 hover:bg-stone-50 transition-all text-sm font-semibold cursor-pointer text-center"
              >
                Keep Free Basic Tier (2 swipes/day)
              </button>
            </div>

            {/* Footer Trust badging */}
            <div className="flex items-center justify-center gap-6 text-[10px] text-stone-500 font-medium">
              <span className="flex items-center gap-1">
                <Shield className="w-3 h-3" /> SSL Secured
              </span>
              <span className="flex items-center gap-1">
                <CreditCard className="w-3 h-3" /> Sandbox Ready
              </span>
            </div>
          </div>
        ) : (
          <div className="space-y-6 py-4 text-center">
            {/* Success Icon */}
            <div className="mx-auto w-16 h-16 rounded-full bg-emerald-50 border border-emerald-200 flex items-center justify-center animate-bounce">
              <Check className="w-8 h-8 text-emerald-600" />
            </div>

            {/* Success Message */}
            <div className="space-y-2">
              <h3 className="text-3xl font-extrabold font-outfit text-stone-900">
                You're on the List!
              </h3>
              <p className="text-stone-600 text-sm max-w-sm mx-auto leading-relaxed">
                Thank you for your interest and feedback on LabMatch Pro! Since we are currently in invite-only private beta, we won't charge you today.
              </p>
              <p className="text-stone-500 text-xs max-w-xs mx-auto leading-relaxed pt-2 font-semibold text-emerald-700">
                🎉 Your 20 daily swipes have been unlocked for today! We've noted your pricing feedback.
              </p>
            </div>

            {/* Continue Button */}
            <button
              onClick={onClose}
              className="w-full py-4 px-6 rounded-xl bg-[#1e3a4a] hover:bg-[#163040] text-white font-bold transition-all duration-200 cursor-pointer shadow-md hover:shadow-lg hover:shadow-[#1e3a4a]/10 text-center flex items-center justify-center gap-2 border-0"
            >
              Back to Dashboard
            </button>
          </div>
        )}
      </GlassCard>
      </div>
    </div>,
    document.body
  );
};

export default PaywallModal;
