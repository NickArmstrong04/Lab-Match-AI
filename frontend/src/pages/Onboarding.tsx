import React, { useState, useRef, useEffect } from 'react';
import { Upload, FileText, CheckCircle2, AlertCircle, ChevronRight, RefreshCw } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import api from '../api/axios';
import { trackEvent, setStudentId } from '../utils/analytics';

export type OnboardingEntry = 'new' | 'returning';

interface OnboardingProps {
  onComplete: (data: { resumeName: string; researchInterests: string; matches: any[]; studentId?: string; studentName?: string; location?: string }) => void;
  entry?: OnboardingEntry;
  onBackToCover?: () => void;
  showHero?: boolean;
  lockNewProfile?: boolean;
  lockReturning?: boolean;
}

export const Onboarding: React.FC<OnboardingProps> = ({
  onComplete,
  entry = 'new',
  onBackToCover,
  showHero: showHeroProp,
  lockNewProfile = false,
  lockReturning = false,
}) => {
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [researchInterests, setResearchInterests] = useState('');
  const [fullName, setFullName] = useState('');
  const [emailAddress, setEmailAddress] = useState('');
  const [location, setLocation] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisStep, setAnalysisStep] = useState<number>(0);
  const [onboardingStage, setOnboardingStage] = useState<'form' | 'auth_setup'>('form');
  const [tempCompletedData, setTempCompletedData] = useState<any>(null);
  const [password, setPassword] = useState('');
  const [isSavingPassword, setIsSavingPassword] = useState(false);
  const [isReturningUser, setIsReturningUser] = useState(entry === 'returning' || lockReturning);
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [isGoogleConnected, setIsGoogleConnected] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [hasInteracted, setHasInteracted] = useState(false);

  // Suggested keywords to prompt student typing
  const interestPrompts = [
    "CRISPR-Cas9 gene editing",
    "Deep learning for protein folding",
    "Microfluidic organ-on-a-chip",
    "Somatic mutations in glioma",
    "Single-cell RNA-sequencing"
  ];

  // Telemetry: Track page view on mount
  useEffect(() => {
    trackEvent('view_page', 'onboarding', 'page_view');
  }, []);

  useEffect(() => {
    if (lockReturning) {
      setIsReturningUser(true);
    } else if (lockNewProfile) {
      setIsReturningUser(false);
    } else {
      setIsReturningUser(entry === 'returning');
    }
  }, [entry, lockReturning, lockNewProfile]);

  const handleInteraction = () => {
    if (!hasInteracted) {
      setHasInteracted(true);
      trackEvent('onboarding_started', 'onboarding', 'action');
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const uploadResume = async (selectedFile: File) => {
    if (selectedFile.type !== 'application/pdf') {
      setErrorMsg('Please upload a PDF file only.');
      setUploadStatus('error');
      return;
    }

    setFile(selectedFile);
    setUploadStatus('loading');
    setUploadProgress(40);
    setErrorMsg('');

    // Telemetry: track file selection
    trackEvent('onboarding_resume_selected', 'onboarding', 'action', {
      file_name: selectedFile.name,
      file_size_bytes: selectedFile.size
    });

    // Simulate premium local parsing progress prior to form submit
    setTimeout(() => {
      setUploadProgress(100);
      setUploadStatus('success');
    }, 600);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      uploadResume(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      uploadResume(e.target.files[0]);
    }
  };

  const triggerFileSelect = () => {
    fileInputRef.current?.click();
  };

  const resetUpload = () => {
    setFile(null);
    setUploadStatus('idle');
    setUploadProgress(0);
    setErrorMsg('');
  };

  const appendInterest = (term: string) => {
    handleInteraction();
    setResearchInterests((prev) => {
      const trimmed = prev.trim();
      if (!trimmed) return term;
      if (trimmed.endsWith(',')) return `${trimmed} ${term}`;
      return `${trimmed}, ${term}`;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file && !researchInterests.trim()) {
      setErrorMsg('Please either upload a CV/Resume (PDF) OR detail your research interests.');
      if (!file) setUploadStatus('error');
      return;
    }
    if (!fullName.trim() || !emailAddress.trim()) {
      setErrorMsg('Please provide your Full Name and Email Address.');
      return;
    }

    const submitStartTime = Date.now();

    // Telemetry: track onboarding submission attempt
    trackEvent('onboarding_submit_attempt', 'onboarding', 'action', {
      has_resume: !!file,
      interests_length: researchInterests.length,
      is_login: false
    });

    setIsAnalyzing(true);
    setAnalysisStep(1); // Stage 1: Ingesting credentials
    setErrorMsg('');

    try {
      const authId = crypto.randomUUID();
      const name = fullName;
      const email = emailAddress;

      const formData = new FormData();
      formData.append('auth_id', authId);
      formData.append('name', name);
      formData.append('email', email);
      formData.append('research_interests', researchInterests);
      if (location.trim()) {
        formData.append('location', location.trim());
      }
      if (file) {
        formData.append('file', file);
      }

      // Add small transition pacing so step labels are readable (800ms)
      await new Promise(resolve => setTimeout(resolve, fullName === "Sarah Nguyen" ? 600 : 800));
      setAnalysisStep(2); // Stage 2: Distilling scientific interests with Gemini

      let analyzeData;
      let studentId;
      let matchedGrants;

      if (fullName === "Sarah Nguyen") {
        studentId = "11111111-1111-1111-1111-111111111111";
        analyzeData = {
          status: 'success',
          student: {
            id: studentId,
            auth_id: studentId,
            name: fullName,
            email: emailAddress,
            research_interests: researchInterests,
            structured_competencies: {
              skills: ["Deep Learning", "Genomics", "Somatic Mutations", "Transcription Factors", "Python"],
              education: "B.S. in Biomedical Science (Stanford University)",
              synthesized_summary: "Pre-med student at Stanford University focused on applying deep neural networks to map somatic cancer mutations and predict genomic transcription factor shifts.",
              recommended_roles: ["Computational Biologist Research Assistant", "Clinical Data Analyst"],
              location: "Stanford University"
            },
            domain_tags: ["Deep Learning", "Genomics", "Oncology"]
          }
        };

        matchedGrants = [
          {
            "id": "22222222-2222-2222-2222-222222222222",
            "pi_name": "Dr. Chen Wei",
            "pi_email": "c.wei@berkeley.edu",
            "institution": "UC Berkeley",
            "university": "UC Berkeley",
            "department": "EECS",
            "title": "Autonomous Robotics for Pediatric Surgical Assistance",
            "grant_title": "Autonomous Robotics for Pediatric Surgical Assistance",
            "agency": "NSF",
            "funding_source": "NSF",
            "award_amount": 540000.0,
            "project_start": "2026-07-15",
            "project_end": "2028-07-14",
            "abstract": "Developing computer vision algorithms and reinforcement learning policies to assist surgeons in pediatric micro-surgery. The project targets automated tool tracking, semantic segmentation of blood vessels, and real-time path planning in delicate environments.",
            "score": 68,
            "compatibility_score": 68,
            "matching_skills": ["python"],
            "missing_skills": ["computer vision", "robotics", "reinforcement learning"],
            "methodologies": ["Computer Vision", "Robotics", "Reinforcement Learning"],
            "recommended_role": "Research Assistant",
            "status": null,
            "location_match": false
          },
          {
            "id": "11111111-1111-1111-1111-111111111111",
            "pi_name": "Dr. Sarah Jenkins",
            "pi_email": "s.jenkins@stanford.edu",
            "institution": "Stanford University",
            "university": "Stanford University",
            "department": "Bioengineering",
            "title": "Deep Learning for Genomic Mutation Analysis",
            "grant_title": "Deep Learning for Genomic Mutation Analysis",
            "agency": "NIH",
            "funding_source": "NIH",
            "award_amount": 750000.0,
            "project_start": "2026-09-01",
            "project_end": "2029-08-31",
            "abstract": "This research focuses on utilizing deep neural networks to identify non-coding genomic variants associated with cardiovascular diseases. We apply transformer models and convolutional neural networks to predict splicing disruption and transcription factor binding shifts.",
            "score": 98,
            "compatibility_score": 98,
            "matching_skills": ["deep learning", "genomics", "transformers", "python"],
            "missing_skills": [],
            "methodologies": ["Deep Learning", "Genomics", "Transformers", "Python"],
            "recommended_role": "Computational Biologist Research Assistant",
            "status": null,
            "location_match": true
          }
        ];

        // Snappy simulation pauses for the progress steps - optimized for a smooth, high-fidelity 2.4s total visual pacing on ads!
        await new Promise(resolve => setTimeout(resolve, 600));
        setAnalysisStep(2);
        await new Promise(resolve => setTimeout(resolve, 600));
        setAnalysisStep(3);
        await new Promise(resolve => setTimeout(resolve, 600));
        setAnalysisStep(4);
        await new Promise(resolve => setTimeout(resolve, 600));
      } else if (fullName === "Elena Rostova") {
        studentId = "33333333-3333-3333-3333-333333333333";
        analyzeData = {
          status: 'success',
          student: {
            id: studentId,
            auth_id: studentId,
            name: fullName,
            email: emailAddress,
            research_interests: researchInterests,
            structured_competencies: {
              skills: ["Molecular Biology", "CRISPR-Cas9", "Stem Cells", "Epigenetics", "Python"],
              education: "B.S. in Molecular Biology (Harvard University)",
              synthesized_summary: "Molecular biology student at Harvard University interested in stem cell screening and CRISPR base editing.",
              recommended_roles: ["Molecular Biology Research Assistant", "Stem Cell Laboratory Intern"],
              location: "Harvard University"
            },
            domain_tags: ["Molecular Biology", "CRISPR-Cas9", "Epigenetics"]
          }
        };

        matchedGrants = [
          {
            "id": "44444444-4444-4444-4444-444444444444",
            "pi_name": "Dr. Wei-An Lim",
            "pi_email": "w.lim@mit.edu",
            "institution": "MIT",
            "university": "MIT",
            "department": "Biology",
            "title": "Plant Genomes and Environmental Stress Proximity",
            "grant_title": "Plant Genomes and Environmental Stress Proximity",
            "agency": "NSF",
            "funding_source": "NSF",
            "award_amount": 520000.0,
            "project_start": "2026-07-15",
            "project_end": "2028-07-14",
            "abstract": "Investigating epigenetic changes in Arabidopsis thaliana under high salinity and drought conditions to maximize crop yield. We examine histones and chromatin dynamics using next-generation sequencing libraries and plant microfluidic arrays.",
            "score": 58,
            "compatibility_score": 58,
            "matching_skills": ["python"],
            "missing_skills": ["plant biology", "epigenetics", "microfluidics"],
            "methodologies": ["Plant Biology", "Epigenetics", "Microfluidics"],
            "recommended_role": "Research Assistant",
            "status": null,
            "location_match": false
          },
          {
            "id": "33333333-3333-3333-3333-333333333333",
            "pi_name": "Dr. Sternberg",
            "pi_email": "s.sternberg@harvard.edu",
            "institution": "Harvard University",
            "university": "Harvard University",
            "department": "Molecular & Cellular Biology",
            "title": "Precision Epigenetic Base Editing in Human Stem Cells",
            "grant_title": "Precision Epigenetic Base Editing in Human Stem Cells",
            "agency": "NIH",
            "funding_source": "NIH",
            "award_amount": 820000.0,
            "project_start": "2026-09-01",
            "project_end": "2029-08-31",
            "abstract": "Developing next-generation CRISPR-Cas base editors to modify genomic loci in hematopoietic stem cells. We optimize target specificity and construct engineered guide RNAs to achieve highly localized nucleobase transitions and study disease phenotypic recovery.",
            "score": 98,
            "compatibility_score": 98,
            "matching_skills": ["molecular biology", "crispr-cas9", "stem cells", "epigenetics"],
            "missing_skills": [],
            "methodologies": ["Molecular Biology", "CRISPR-Cas9", "Stem Cells", "Epigenetics"],
            "recommended_role": "Molecular Biology Research Assistant",
            "status": null,
            "location_match": true
          }
        ];

        // Snappy simulation pauses for the progress steps - optimized for a smooth, high-fidelity 2.4s total visual pacing on ads!
        await new Promise(resolve => setTimeout(resolve, 600));
        setAnalysisStep(2);
        await new Promise(resolve => setTimeout(resolve, 600));
        setAnalysisStep(3);
        await new Promise(resolve => setTimeout(resolve, 600));
        setAnalysisStep(4);
        await new Promise(resolve => setTimeout(resolve, 600));
      } else {
        // Trigger single-pass multipart analysis
        const analyzeResp = await api.post('/profile/analyze', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });

        analyzeData = analyzeResp.data;
        if (analyzeData.status !== 'success' && analyzeData.status !== 'partial_success') {
          throw new Error(analyzeData.message || 'Profile synthesis failed.');
        }

        studentId = analyzeData.student.id || analyzeData.student.auth_id;
        if (!studentId || studentId === 'undefined') {
          throw new Error('Failed to retrieve a valid student ID from profile analysis.');
        }
        
        setAnalysisStep(3); // Stage 3: Resolving home-campus location proximity checks
        await new Promise(resolve => setTimeout(resolve, 650));

        setAnalysisStep(4); // Stage 4: Executing live pgvector similarity matching against federal grants
        await new Promise(resolve => setTimeout(resolve, 600));
        
        // Fetch matched research grants: Default to local campus matches first
        let matchResp = await api.get(`/grants/matches?student_id=${studentId}&threshold=0.2&limit=5&local_only=true`);
        matchedGrants = matchResp.data;

        // Fallback: If no local matches are found, fetch all grants
        if (!matchedGrants || matchedGrants.length === 0) {
          matchResp = await api.get(`/grants/matches?student_id=${studentId}&threshold=0.2&limit=5&local_only=false`);
          matchedGrants = matchResp.data;
        }
      }

      setTempCompletedData({
        resumeName: file ? file.name : 'No Resume Provided',
        researchInterests: researchInterests,
        matches: matchedGrants,
        studentId: studentId,
        studentName: name,
        location: location.trim(),
        synthesis_duration_ms: Date.now() - submitStartTime,
        has_parser_error: analyzeData.status === 'partial_success'
      });
      setOnboardingStage('auth_setup');
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.response?.data?.detail || err.message || 'Communication with the matching engine failed.');
    } finally {
      setIsAnalyzing(false);
      setAnalysisStep(0);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!emailAddress.trim() || !password.trim()) {
      setErrorMsg('Please enter both your email address and password.');
      return;
    }

    setIsLoggingIn(true);
    setErrorMsg('');

    // Telemetry: track login submit attempt
    trackEvent('onboarding_submit_attempt', 'onboarding', 'action', {
      is_login: true
    });

    try {
      // 1. Verify credentials and load student profile
      const loginResp = await api.post('/auth/login', {
        email: emailAddress.trim(),
        password: password.trim()
      });

      const student = loginResp.data.student;
      const studentId = student.id || student.auth_id;

      // Telemetry: track successful login completion
      setStudentId(studentId);
      trackEvent('onboarding_completed', 'onboarding', 'action', {
        student_id: studentId,
        save_method: 'login'
      });

      // 2. Fetch matched grants for the returning student
      let matchResp = await api.get(`/grants/matches?student_id=${studentId}&threshold=0.2&limit=5&local_only=true`);
      let matchedGrants = matchResp.data;

      if (!matchedGrants || matchedGrants.length === 0) {
        matchResp = await api.get(`/grants/matches?student_id=${studentId}&threshold=0.2&limit=5&local_only=false`);
        matchedGrants = matchResp.data;
      }

      // 3. Complete onboarding and route to dashboard
      onComplete({
        resumeName: student.resume_url ? 'Saved Resume' : 'No Resume Provided',
        researchInterests: student.research_interests || '',
        matches: matchedGrants,
        studentId: studentId,
        studentName: student.name,
        location: student.location || ''
      });
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.response?.data?.detail || err.message || 'Login failed. Please verify your credentials.');
    } finally {
      setIsLoggingIn(false);
    }
  };

  const handleSavePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) {
      setErrorMsg('Please enter a password.');
      return;
    }

    setIsSavingPassword(true);
    setErrorMsg('');

    try {
      await api.post('/auth/save-password', {
        student_id: tempCompletedData.studentId,
        password: password.trim()
      });

      // Telemetry: track successful password save completion
      if (tempCompletedData?.studentId) {
        setStudentId(tempCompletedData.studentId);
        trackEvent('onboarding_completed', 'onboarding', 'action', {
          student_id: tempCompletedData.studentId,
          save_method: 'password',
          synthesis_duration_ms: tempCompletedData.synthesis_duration_ms,
          has_parser_error: tempCompletedData.has_parser_error
        });
      }

      // Complete onboarding and advance to dashboard
      onComplete(tempCompletedData);
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.response?.data?.detail || err.message || 'Failed to save password. Please try again.');
    } finally {
      setIsSavingPassword(false);
    }
  };

  const handleConnectGoogleOnboarding = () => {
    const width = 500;
    const height = 650;
    const left = window.screenX + (window.innerWidth - width) / 2;
    const top = window.screenY + (window.innerHeight - height) / 2;
    const baseUrl = import.meta.env.VITE_API_URL || (window.location.hostname === 'localhost' ? 'http://localhost:8000' : window.location.origin);
    
    // Open OAuth window popup
    window.open(
      `${baseUrl}/auth/google/login?student_id=${tempCompletedData.studentId}`,
      'Google OAuth Handshake',
      `width=${width},height=${height},left=${left},top=${top},status=no,toolbar=no,menubar=no`
    );
  };

  // Listen to Google callback message to automatically complete flow on success
  useEffect(() => {
    const handleOauthMessage = (event: MessageEvent) => {
      if (event.data && event.data.type === "google_oauth_success") {
        console.log("OAuth success during onboarding account connection!");
        setIsGoogleConnected(true);

        // Telemetry: track successful Google OAuth connected completion
        if (tempCompletedData?.studentId) {
          setStudentId(tempCompletedData.studentId);
          trackEvent('onboarding_completed', 'onboarding', 'action', {
            student_id: tempCompletedData.studentId,
            save_method: 'google_oauth',
            synthesis_duration_ms: tempCompletedData.synthesis_duration_ms,
            has_parser_error: tempCompletedData.has_parser_error
          });
        }

        // Automatically proceed after 1s delay
        setTimeout(() => {
          if (tempCompletedData) {
            onComplete(tempCompletedData);
          }
        }, 1000);
      }
    };
    window.addEventListener("message", handleOauthMessage);
    return () => window.removeEventListener("message", handleOauthMessage);
  }, [tempCompletedData]);

  if (onboardingStage === 'auth_setup') {
    return (
      <div className="w-full px-4 sm:px-6 py-6 md:py-8 animate-fade-in flex flex-col items-center justify-center min-h-[70vh]">
        <div className="text-center mb-8 max-w-xl mx-auto shrink-0">
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-[#0d5c5c] font-outfit mb-3 leading-tight">
            🎉 Profile Synthesized Successfully!
          </h1>
          <p className="text-stone-600 text-sm md:text-base leading-relaxed">
            Your semantic research vector and lab matches are ready. Set a password or connect your Google account to save your results permanently (optional).
          </p>
        </div>

        <div className="w-full max-w-md mx-auto">
          <GlassCard className="p-6 md:p-8 space-y-6" glowColor="teal">
            <h2 className="text-lg font-semibold font-outfit text-stone-900 border-b border-stone-100 pb-3">
              Save Your Lab Pipeline (Optional)
            </h2>

            <form onSubmit={handleSavePassword} className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-stone-500 uppercase tracking-wider block">
                  Email Address
                </label>
                <input
                  type="email"
                  value={emailAddress}
                  disabled
                  className="input-field bg-stone-50 border-stone-200 text-stone-500 cursor-not-allowed opacity-80"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-stone-500 uppercase tracking-wider block">
                  Create Account Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter a secure password"
                  className="input-field text-sm"
                  required
                />
              </div>

              {errorMsg && (
                <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start gap-2.5">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" strokeWidth={1.75} />
                  <span>{errorMsg}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={isSavingPassword}
                className="btn-primary w-full py-2.5 text-xs font-bold"
              >
                {isSavingPassword ? (
                  <>Saving Password... <RefreshCw className="w-3.5 h-3.5 animate-spin" /></>
                ) : (
                  <>Create Password & View Matches ➔</>
                )}
              </button>
            </form>

            <div className="relative my-6 flex items-center justify-center">
              <span className="absolute inset-x-0 h-px bg-stone-200"></span>
              <span className="relative px-3 bg-white text-xs font-medium text-stone-400 font-mono">OR</span>
            </div>

            <button
              onClick={handleConnectGoogleOnboarding}
              disabled={isGoogleConnected}
              className={`w-full py-2.5 rounded-lg border font-semibold inline-flex items-center justify-center gap-2.5 transition-all text-xs cursor-pointer ${
                isGoogleConnected 
                  ? 'bg-emerald-50 border-emerald-200 text-emerald-800' 
                  : 'bg-white border-stone-300 hover:border-stone-400 text-stone-700 hover:bg-stone-50'
              }`}
            >
              {isGoogleConnected ? (
                <>
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  Google Account Connected!
                </>
              ) : (
                <>
                  <svg className="w-4 h-4 block" viewBox="0 0 24 24">
                    <path
                      fill="#4285F4"
                      d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                    />
                    <path
                      fill="#34A853"
                      d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                    />
                    <path
                      fill="#FBBC05"
                      d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                    />
                    <path
                      fill="#EA4335"
                      d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                    />
                  </svg>
                  Connect Google Account
                </>
              )}
            </button>

            <div className="border-t border-stone-100 pt-4 mt-6 flex justify-center">
              <button
                onClick={() => {
                  // Telemetry: track skipped auth completed
                  if (tempCompletedData?.studentId) {
                    setStudentId(tempCompletedData.studentId);
                    trackEvent('onboarding_completed', 'onboarding', 'action', {
                      student_id: tempCompletedData.studentId,
                      save_method: 'skip',
                      synthesis_duration_ms: tempCompletedData.synthesis_duration_ms,
                      has_parser_error: tempCompletedData.has_parser_error
                    });
                  }
                  onComplete(tempCompletedData);
                }}
                className="px-4 py-2 rounded-lg text-stone-500 hover:text-stone-800 hover:bg-stone-50 transition-colors text-xs font-semibold flex items-center gap-1.5 cursor-pointer border-0 bg-transparent"
              >
                Skip & View Matches directly ➔
              </button>
            </div>
          </GlassCard>
        </div>
      </div>
    );
  }

  const showHero = showHeroProp ?? !onBackToCover;
  const showAccountTabs = !lockNewProfile && !lockReturning;

  return (
    <div className="w-full px-4 sm:px-6 py-6 md:py-8 animate-fade-in">
      {showHero && (
        <div className="onboarding-hero mb-8 md:mb-10 shrink-0">
          <div className="w-full max-w-2xl mx-auto onboarding-hero-inner">
            <div
              className={`onboarding-hero-header${onBackToCover ? '' : ' onboarding-hero-header--solo'}`}
            >
              {onBackToCover && (
                <button type="button" onClick={onBackToCover} className="onboarding-back-home">
                  ← Back to home
                </button>
              )}
              <h1 className="onboarding-hero-title">
                {isReturningUser ? 'Welcome Back!' : 'Build Your Research Profile'}
              </h1>
            </div>
            <p className="onboarding-hero-subtitle">
              {isReturningUser
                ? 'Login with your email and password to load your academic CV narrative, research interests, and active lab matches.'
                : 'Upload your academic credentials and detail your research interests to align immediately with active, fully-funded NIH & NSF labs.'}
            </p>
          </div>
        </div>
      )}

      {!showHero && onBackToCover && (
        <div className="onboarding-back-home-row mb-4">
          <button type="button" onClick={onBackToCover} className="onboarding-back-home">
            ← Back to home
          </button>
        </div>
      )}

      <div className="w-full max-w-2xl mx-auto">
        <GlassCard
          className="relative flex flex-col w-full min-h-[28rem] p-6 md:p-8"
          glowColor={uploadStatus === 'success' ? 'teal' : 'none'}
        >
          {showAccountTabs && (
            <div className="flex border-b border-stone-200 pb-3 mb-6 gap-4 shrink-0 justify-center sm:justify-start">
              <button
                type="button"
                onClick={() => {
                  setIsReturningUser(false);
                  setErrorMsg('');
                }}
                className={`px-3 py-1.5 text-xs font-bold border-b-2 transition-all cursor-pointer bg-transparent border-0 ${
                  !isReturningUser
                    ? 'text-[#0d5c5c] border-[#0d5c5c]'
                    : 'text-stone-400 border-transparent hover:text-stone-600'
                }`}
              >
                Build New Profile
              </button>
              <button
                type="button"
                onClick={() => {
                  setIsReturningUser(true);
                  setErrorMsg('');
                }}
                className={`px-3 py-1.5 text-xs font-bold border-b-2 transition-all cursor-pointer bg-transparent border-0 ${
                  isReturningUser
                    ? 'text-[#0d5c5c] border-[#0d5c5c]'
                    : 'text-stone-400 border-transparent hover:text-stone-600'
                }`}
              >
                Returning Student Login
              </button>
            </div>
          )}

          {isReturningUser ? (
            /* RETURNING STUDENT LOGIN FORM */
            <form onSubmit={handleLogin} className="space-y-5 flex-1 flex flex-col justify-between">
              <div className="space-y-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-stone-500 uppercase tracking-wider block">
                    Email Address
                  </label>
                  <input
                    type="email"
                    value={emailAddress}
                    onChange={(e) => setEmailAddress(e.target.value)}
                    onFocus={handleInteraction}
                    placeholder="Enter your email address"
                    className="input-field text-sm"
                    required
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-semibold text-stone-500 uppercase tracking-wider block">
                    Password
                  </label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onFocus={handleInteraction}
                    placeholder="Enter your account password"
                    className="input-field text-sm"
                    required
                  />
                </div>

                {errorMsg && (
                  <div className="p-3.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start gap-2.5">
                    <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" strokeWidth={1.75} />
                    <span>{errorMsg}</span>
                  </div>
                )}
              </div>

              <div className="shrink-0 mt-6 pt-5 border-t border-stone-200 flex justify-center sm:justify-end">
                <button
                  type="submit"
                  disabled={isLoggingIn}
                  className="btn-primary w-full sm:w-auto py-2.5 px-6 font-bold text-xs"
                >
                  {isLoggingIn ? (
                    <>
                      Logging In... <RefreshCw className="w-4 h-4 animate-spin" />
                    </>
                  ) : (
                    <>
                      Login ➔
                    </>
                  )}
                </button>
              </div>
            </form>
          ) : (
            /* NEW STUDENT PROFILE SIGNUP FORM */
            <form
              onSubmit={handleSubmit}
              className="flex flex-col flex-1 min-h-0 gap-5"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={handleFileChange}
              />

              <div className="flex flex-col flex-1 min-h-0 gap-5">
                <div className="shrink-0 text-center sm:text-left">
                  <h2 className="text-xl font-semibold font-outfit text-stone-900 mb-1.5 animate-fade-in">
                    Research Profile
                  </h2>
                  <p className="text-stone-600 text-sm leading-relaxed">
                    Add your CV for background parsing, then describe your scientific goals and research interests.
                  </p>
                </div>

                <div className="shrink-0 w-full">
                  {uploadStatus === 'idle' || uploadStatus === 'error' ? (
                    <div
                      onDragEnter={handleDrag}
                      onDragOver={handleDrag}
                      onDragLeave={handleDrag}
                      onDrop={handleDrop}
                      className="w-full"
                    >
                      <button
                        type="button"
                        onClick={triggerFileSelect}
                        className={`
                          w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg border text-sm font-medium transition-colors duration-200 cursor-pointer
                          ${dragActive
                            ? 'border-[#1e3a4a] bg-[#e6f0f0] text-[#1e3a4a]'
                            : uploadStatus === 'error' && !file
                              ? 'border-rose-300 bg-rose-50 text-rose-800 hover:bg-rose-100/80'
                              : 'border-stone-300 bg-stone-50 text-stone-700 hover:border-stone-400 hover:bg-white'}
                        `}
                      >
                        <Upload className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                        <span>Upload Academic CV / Resume (PDF)</span>
                        <span className="hidden sm:inline text-stone-400 font-normal">· drag & drop</span>
                      </button>
                    </div>
                  ) : uploadStatus === 'loading' ? (
                    <div className="w-full flex items-center gap-3 py-2.5 px-4 rounded-lg border border-stone-200 bg-stone-50">
                      <RefreshCw className="w-4 h-4 text-[#0d5c5c] animate-spin shrink-0" strokeWidth={1.75} />
                      <div className="flex-1 min-w-0">
                        <p className="text-stone-800 text-xs font-medium truncate mb-1.5">
                          Extracting publications & skills…
                        </p>
                        <div className="w-full bg-stone-200 h-1 rounded-full overflow-hidden">
                          <div
                            className="bg-[#0d5c5c] h-full rounded-full transition-all duration-300"
                            style={{ width: `${uploadProgress}%` }}
                          />
                        </div>
                      </div>
                      <span className="text-stone-500 text-xs font-medium shrink-0">{uploadProgress}%</span>
                    </div>
                  ) : (
                    <div className="w-full flex items-center gap-2 py-2 px-3 rounded-lg border border-[#c5dddd] bg-[#f4f9f9]">
                      <CheckCircle2 className="w-4 h-4 text-[#0d5c5c] shrink-0" strokeWidth={1.75} />
                      <FileText className="w-4 h-4 text-[#1e3a4a] shrink-0 hidden sm:block" strokeWidth={1.75} />
                      <span className="flex-1 min-w-0 text-sm text-stone-800 font-mono truncate">
                        {file?.name}
                      </span>
                      <button
                        type="button"
                        onClick={resetUpload}
                        className="shrink-0 px-2.5 py-1 rounded-md text-xs font-semibold text-stone-600 hover:text-stone-900 hover:bg-white border border-transparent hover:border-stone-200 transition-colors cursor-pointer"
                      >
                        Replace
                      </button>
                    </div>
                  )}
                </div>

                <div className="flex flex-col flex-1 min-h-0 gap-4">
                  <div className="shrink-0 grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
                    <input
                      type="text"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      onFocus={handleInteraction}
                      placeholder="Full Name"
                      className="input-field text-sm"
                      required
                    />
                    <input
                      type="email"
                      value={emailAddress}
                      onChange={(e) => setEmailAddress(e.target.value)}
                      onFocus={handleInteraction}
                      placeholder="Email Address"
                      className="input-field text-sm"
                      required
                    />
                    <input
                      type="text"
                      value={location}
                      onChange={(e) => setLocation(e.target.value)}
                      onFocus={handleInteraction}
                      placeholder="University / Affiliation"
                      className="input-field text-sm"
                      required
                    />
                  </div>

                  <textarea
                    value={researchInterests}
                    onChange={(e) => setResearchInterests(e.target.value)}
                    onFocus={handleInteraction}
                    placeholder="Example: I am deeply interested in studying neurodegenerative diseases. Specifically, leveraging high-content screening systems and deep learning algorithms to predict cellular drug target engagement..."
                    className="input-field flex-1 min-h-[10rem] resize-none leading-relaxed text-sm"
                  />

                  <div className="shrink-0">
                    <p className="text-xs font-semibold text-stone-500 uppercase tracking-wider mb-2.5">
                      Suggested Research Vectors (Click to append)
                    </p>
                    <div className="flex flex-wrap justify-center sm:justify-start gap-2">
                      {interestPrompts.map((term, index) => (
                        <button
                          key={index}
                          type="button"
                          onClick={() => appendInterest(term)}
                          className="chip-suggestion cursor-pointer"
                        >
                          + {term}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {errorMsg && (
                  <div className="shrink-0 p-3.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-sm flex items-start gap-2.5">
                    <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" strokeWidth={1.75} />
                    <span>{errorMsg}</span>
                  </div>
                )}
              </div>

              <div className="shrink-0 mt-6 pt-5 border-t border-stone-200 flex justify-center sm:justify-end">
                <button
                  type="submit"
                  disabled={isAnalyzing || uploadStatus === 'loading'}
                  className="btn-primary w-full sm:w-auto text-xs font-bold py-2.5 px-6"
                >
                  {isAnalyzing ? (
                    <>
                      Synthesizing Profile... <RefreshCw className="w-4 h-4 animate-spin" />
                    </>
                  ) : (
                    <>
                      Analyze & Sync Matches <ChevronRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </div>
            </form>
          )}
        </GlassCard>
      </div>

      {isAnalyzing && (
        <div className="fixed inset-0 bg-stone-900/40 backdrop-blur-md flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="w-full max-w-md bg-white border border-stone-200 rounded-2xl shadow-2xl p-6 md:p-8 space-y-6 text-center animate-fade-in">
            <div className="w-14 h-14 rounded-full bg-[#e6f0f0] border border-[#c5dddd] flex items-center justify-center mx-auto relative overflow-hidden">
              <RefreshCw className="w-7 h-7 text-[#0d5c5c] animate-spin" />
            </div>
            
            <div className="space-y-2">
              <h3 className="text-lg font-semibold font-outfit text-stone-900 tracking-tight">
                Synthesizing Your Research Profile
              </h3>
              <p className="text-stone-500 text-xs leading-relaxed max-w-xs mx-auto">
                Please wait while our backend pipeline builds your semantic research vector index.
              </p>
            </div>

            {/* Steps checklist with dynamic high contrast colors */}
            <div className="space-y-3.5 text-left border-t border-b border-stone-100 py-5">
              <div className="flex items-center gap-3 text-xs">
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold border transition-colors duration-300 ${
                  analysisStep > 1 
                    ? 'bg-[#e6f7f0] border-[#b2ddcf] text-[#0d5c48]' 
                    : analysisStep === 1 
                      ? 'bg-blue-50 border-blue-200 text-blue-800 animate-pulse' 
                      : 'bg-stone-50 border-stone-200 text-stone-400'
                }`}>
                  {analysisStep > 1 ? '✓' : '1'}
                </span>
                <span className={`transition-colors duration-300 ${analysisStep === 1 ? 'font-semibold text-stone-900' : analysisStep > 1 ? 'text-stone-500' : 'text-stone-400'}`}>
                  📂 Ingesting academic CV credentials & reading text stream
                </span>
              </div>

              <div className="flex items-center gap-3 text-xs">
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold border transition-colors duration-300 ${
                  analysisStep > 2 
                    ? 'bg-[#e6f7f0] border-[#b2ddcf] text-[#0d5c48]' 
                    : analysisStep === 2 
                      ? 'bg-blue-50 border-blue-200 text-blue-800 animate-pulse' 
                      : 'bg-stone-50 border-stone-200 text-stone-400'
                }`}>
                  {analysisStep > 2 ? '✓' : '2'}
                </span>
                <span className={`transition-colors duration-300 ${analysisStep === 2 ? 'font-semibold text-stone-900' : analysisStep > 2 ? 'text-stone-500' : 'text-stone-400'}`}>
                  🧠 Distilling research interests & scientific tags with Gemini
                </span>
              </div>

              <div className="flex items-center gap-3 text-xs">
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold border transition-colors duration-300 ${
                  analysisStep > 3 
                    ? 'bg-[#e6f7f0] border-[#b2ddcf] text-[#0d5c48]' 
                    : analysisStep === 3 
                      ? 'bg-blue-50 border-blue-200 text-blue-800 animate-pulse' 
                      : 'bg-stone-50 border-stone-200 text-stone-400'
                }`}>
                  {analysisStep > 3 ? '✓' : '3'}
                </span>
                <span className={`transition-colors duration-300 ${analysisStep === 3 ? 'font-semibold text-stone-900' : analysisStep > 3 ? 'text-stone-500' : 'text-stone-400'}`}>
                  📍 Resolving university home-campus location proximity checks
                </span>
              </div>

              <div className="flex items-center gap-3 text-xs">
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold border transition-colors duration-300 ${
                  analysisStep > 4 
                    ? 'bg-[#e6f7f0] border-[#b2ddcf] text-[#0d5c48]' 
                    : analysisStep === 4 
                      ? 'bg-blue-50 border-blue-200 text-blue-800 animate-pulse' 
                      : 'bg-stone-50 border-stone-200 text-stone-400'
                }`}>
                  {analysisStep > 4 ? '✓' : '4'}
                </span>
                <span className={`transition-colors duration-300 ${analysisStep === 4 ? 'font-semibold text-stone-900' : 'text-stone-400'}`}>
                  ⚡ Executing pgvector similarity search matching active grants
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Onboarding;
