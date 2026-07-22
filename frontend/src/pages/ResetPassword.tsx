import React, { useState } from 'react';
import { AlertCircle, CheckCircle2, RefreshCw, ChevronRight } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import api from '../api/axios';
import { trackEvent, setStudentId } from '../utils/analytics';
import { setToken, saveSession } from '../utils/session';

// Reached only from the emailed reset link (#/reset-password?token=...). App.tsx
// captures the token before its URL-sync effect scrubs it from the address bar,
// and passes it down here; token === null means the link was malformed, hand-typed,
// or revisited via Back after the hash was cleaned.
interface ResetPasswordProps {
  token: string | null;
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
  onBackToSignIn: () => void;
}

const MIN_PASSWORD_LENGTH = 8; // mirrors backend/routers/auth.py MIN_PASSWORD_LENGTH

export const ResetPassword: React.FC<ResetPasswordProps> = ({
  token,
  onComplete,
  onBackToSignIn,
}) => {
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  // The reset itself succeeded but the follow-up match fetch failed. Distinct from
  // errorMsg on purpose: rendering a rose error after the password WAS changed would
  // tell the student their reset failed when it didn't.
  const [resetDoneLoadFailed, setResetDoneLoadFailed] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password.trim().length < MIN_PASSWORD_LENGTH) {
      setErrorMsg(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (password.trim() !== confirmPassword.trim()) {
      setErrorMsg('Passwords do not match.');
      return;
    }

    setIsSubmitting(true);
    setErrorMsg('');

    try {
      const resp = await api.post('/auth/reset-password', {
        token,
        password: password.trim(),
      });

      const student = resp.data.student;
      const studentId = student.id || student.auth_id;

      // Store the session BEFORE the match fetch: the axios interceptor reads the
      // token per-request (same ordering as the login handler in Onboarding.tsx).
      setToken(resp.data.access_token);
      saveSession({
        studentId,
        studentName: student.name,
        location: student.location || '',
        researchInterests: student.research_interests || '',
        resumeName: student.resume_url ? 'Saved Resume' : 'No Resume Provided',
        isAuthenticated: true,
      });

      setStudentId(studentId);
      trackEvent('password_reset_completed', 'onboarding', 'action', {
        student_id: studentId,
      });

      // From here on the password IS reset -- any failure below must not read as a
      // failed reset.
      try {
        let matchResp = await api.get(`/grants/matches?student_id=${studentId}&threshold=0.2&limit=5&local_only=true`);
        let matchedGrants = matchResp.data;
        if (!matchedGrants || matchedGrants.length === 0) {
          matchResp = await api.get(`/grants/matches?student_id=${studentId}&threshold=0.2&limit=5&local_only=false`);
          matchedGrants = matchResp.data;
        }

        onComplete({
          resumeName: student.resume_url ? 'Saved Resume' : 'No Resume Provided',
          researchInterests: student.research_interests || '',
          matches: matchedGrants,
          studentId,
          studentName: student.name,
          email: student.email || '',
          location: student.location || '',
          isAuthenticated: true,
        });
      } catch {
        setResetDoneLoadFailed(true);
      }
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.response?.data?.detail || err.message || 'Password reset failed. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // The one backend message that means "this link is dead" -- offer the re-request
  // path instead of a retry that can never succeed.
  const isDeadLink = errorMsg.toLowerCase().includes('reset link');

  if (token === null) {
    return (
      <div className="w-full px-4 sm:px-6 py-6 md:py-8 animate-fade-in flex flex-col items-center justify-center min-h-[70vh]">
        <div className="w-full max-w-md mx-auto">
          <GlassCard className="p-6 md:p-8 space-y-5" glowColor="rose">
            <h1 className="text-xl font-semibold font-outfit text-stone-900">
              This reset link isn't valid
            </h1>
            <p className="text-sm text-stone-600 leading-relaxed">
              The link is incomplete or has already been used. Request a new one from
              the sign-in page. Reset links expire 30 minutes after they're sent.
            </p>
            <button
              type="button"
              onClick={onBackToSignIn}
              className="btn-primary w-full py-2.5 text-xs font-bold"
            >
              Back to Sign In <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </GlassCard>
        </div>
      </div>
    );
  }

  if (resetDoneLoadFailed) {
    return (
      <div className="w-full px-4 sm:px-6 py-6 md:py-8 animate-fade-in flex flex-col items-center justify-center min-h-[70vh]">
        <div className="w-full max-w-md mx-auto">
          <GlassCard className="p-6 md:p-8 space-y-5" glowColor="teal">
            <div className="flex items-center gap-2.5">
              <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
              <h1 className="text-xl font-semibold font-outfit text-stone-900">
                Your password was reset
              </h1>
            </div>
            <p className="text-sm text-stone-600 leading-relaxed">
              The new password is saved, but we couldn't load your matches just now.
              Sign in to continue to your dashboard.
            </p>
            <button
              type="button"
              onClick={onBackToSignIn}
              className="btn-primary w-full py-2.5 text-xs font-bold"
            >
              Sign In <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </GlassCard>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full px-4 sm:px-6 py-6 md:py-8 animate-fade-in flex flex-col items-center justify-center min-h-[70vh]">
      <div className="text-center mb-8 max-w-xl mx-auto shrink-0">
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-[#0d5c5c] font-outfit mb-3 leading-tight">
          Choose a New Password
        </h1>
        <p className="text-stone-600 text-sm md:text-base leading-relaxed">
          Set a new password for your LabMatch AI account. You'll be signed in
          straight away.
        </p>
      </div>

      <div className="w-full max-w-md mx-auto">
        <GlassCard className="p-6 md:p-8 space-y-6" glowColor="teal">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1">
              <label className="text-xs font-semibold text-stone-500 uppercase tracking-wider block">
                New Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
                className="input-field text-sm"
                autoFocus
                required
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-stone-500 uppercase tracking-wider block">
                Confirm New Password
              </label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter the new password"
                className="input-field text-sm"
                required
              />
            </div>

            {errorMsg && (
              <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start gap-2.5">
                <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" strokeWidth={1.75} />
                <span>
                  {errorMsg}
                  {isDeadLink && (
                    <>
                      {' '}
                      <button
                        type="button"
                        onClick={onBackToSignIn}
                        className="font-semibold underline underline-offset-2 cursor-pointer"
                      >
                        Request a new link
                      </button>
                    </>
                  )}
                </span>
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="btn-primary w-full py-2.5 text-xs font-bold"
            >
              {isSubmitting ? (
                <>Resetting Password... <RefreshCw className="w-3.5 h-3.5 animate-spin" /></>
              ) : (
                <>Reset Password & Sign In <ChevronRight className="w-3.5 h-3.5" /></>
              )}
            </button>
          </form>

          <div className="pt-1 text-center">
            <button
              type="button"
              onClick={onBackToSignIn}
              className="text-xs font-semibold text-stone-500 hover:text-stone-700 cursor-pointer"
            >
              Back to Sign In
            </button>
          </div>
        </GlassCard>
      </div>
    </div>
  );
};

export default ResetPassword;
