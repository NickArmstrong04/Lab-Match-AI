import React, { useState, useEffect } from 'react';
import { Check, X, Shield, Zap, CreditCard } from 'lucide-react';
import GlassCard from './GlassCard';
import { trackEvent } from '../utils/analytics';

interface PaywallModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const PaywallModal: React.FC<PaywallModalProps> = ({ isOpen, onClose }) => {
  const [variant, setVariant] = useState<'subscription' | 'lifetime'>('subscription');
  const [isUpgraded, setIsUpgraded] = useState(false);

  useEffect(() => {
    if (!isOpen) return;

    // Check if variant is already assigned, otherwise assign 50/50 randomly
    let activeVariant = localStorage.getItem('labmatch_ab_variant') as 'subscription' | 'lifetime' | null;
    if (!activeVariant) {
      activeVariant = Math.random() < 0.5 ? 'subscription' : 'lifetime';
      localStorage.setItem('labmatch_ab_variant', activeVariant);
    }
    setVariant(activeVariant);

    // Track modal view event
    trackEvent('paywall_view', 'dashboard', 'action', {
      variant: activeVariant,
      price: activeVariant === 'subscription' ? '$4.99/mo' : '$4.99 one-time'
    });
  }, [isOpen]);

  if (!isOpen) return null;

  const priceText = variant === 'subscription' ? '$4.99/month' : '$4.99 one-time';
  const ctaText = variant === 'subscription' ? 'Unlock Unlimited Swipes ($4.99/mo)' : 'Get Lifetime Access ($4.99 one-time)';

  const handleUpgrade = () => {
    // Log conversion event
    trackEvent('paywall_upgrade_click', 'dashboard', 'action', {
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-stone-950/80 backdrop-blur-md animate-fade-in">
      <GlassCard 
        className="relative w-full max-w-lg overflow-hidden flex flex-col p-8 bg-white border border-stone-200 text-stone-900 shadow-2xl rounded-3xl"
        glowColor="none"
      >
        {/* Close Button */}
        <button
          onClick={handleClose}
          className="absolute top-4 right-4 p-2 rounded-full text-stone-400 hover:text-stone-700 hover:bg-stone-100 transition-colors cursor-pointer"
          aria-label="Close"
        >
          <X className="w-5 h-5" />
        </button>

        {!isUpgraded ? (
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
                Aligning student vectors with federal NIH & NSF grants takes serious compute power. Upgrade to unlock full research potential.
              </p>
            </div>

            {/* Core Features List */}
            <div className="space-y-3 bg-stone-50 border border-stone-200 rounded-2xl p-5 text-sm">
              <div className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-stone-100 border border-stone-200 flex items-center justify-center shrink-0 mt-0.5">
                  <Check className="w-3 h-3 text-stone-600" />
                </div>
                <div>
                  <strong className="text-stone-900 font-semibold">Unlimited Swiping & Deck Restarts</strong>
                  <p className="text-stone-500 text-xs">Swipe through hundreds of NIH & NSF grants across the country.</p>
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
                  <strong className="text-stone-900 font-semibold">Direct Gmail Integration</strong>
                  <p className="text-stone-500 text-xs">Send curated emails directly from your student inbox in one click.</p>
                </div>
              </div>
            </div>

            {/* Price Box */}
            <div className="text-center py-4 bg-stone-50 border border-stone-200 rounded-2xl">
              <span className="text-stone-500 text-xs font-semibold uppercase tracking-widest">
                {variant === 'subscription' ? 'Subscription Rate' : 'One-Time Payment'}
              </span>
              <div className="text-4xl font-extrabold text-stone-900 mt-1 tracking-tight font-mono">
                {priceText}
              </div>
              <span className="text-stone-600 text-xs font-medium block mt-1">
                🔒 Safe & secure sandbox validation
              </span>
            </div>

            {/* Checkout / Conversion Call to Action */}
            <div className="space-y-3">
              <button
                onClick={handleUpgrade}
                className="w-full py-4 px-6 rounded-xl bg-[#1e3a4a] hover:bg-[#163040] text-white font-bold transition-all duration-200 cursor-pointer shadow-md hover:shadow-lg hover:shadow-[#1e3a4a]/10 text-center flex items-center justify-center gap-2 border-0"
              >
                <Zap className="w-5 h-5 fill-current" />
                {ctaText}
              </button>
              
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
                Thank you for your interest in LabMatch Pro! Since we are currently in invite-only private beta, we won't charge you today.
              </p>
              <p className="text-stone-500 text-xs max-w-xs mx-auto leading-relaxed pt-2">
                We've noted your price preference ({priceText}) and marked your profile as an early adapter. We will email you the moment Stripe payments are activated!
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
  );
};

export default PaywallModal;
