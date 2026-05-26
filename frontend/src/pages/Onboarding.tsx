import React, { useState, useRef } from 'react';
import { Upload, FileText, CheckCircle2, AlertCircle, ChevronRight, RefreshCw, Database, ScanSearch, Mail } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import api from '../api/axios';

interface OnboardingProps {
  onComplete: (data: { resumeName: string; researchInterests: string; matches: any[]; studentId?: string; studentName?: string }) => void;
}

export const Onboarding: React.FC<OnboardingProps> = ({ onComplete }) => {
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [researchInterests, setResearchInterests] = useState('');
  const [fullName, setFullName] = useState('');
  const [emailAddress, setEmailAddress] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Suggested keywords to prompt student typing
  const interestPrompts = [
    "CRISPR-Cas9 gene editing",
    "Deep learning for protein folding",
    "Microfluidic organ-on-a-chip",
    "Somatic mutations in glioma",
    "Single-cell RNA-sequencing"
  ];

  const whyUseBlocks = [
    {
      icon: Database,
      title: 'Live federal grant alignment',
      description:
        'Surface actively funded NIH and NSF labs that overlap with your stated interests and parsed background—not stale job boards or generic listings.',
    },
    {
      icon: ScanSearch,
      title: 'CV-aware profile synthesis',
      description:
        'Upload a PDF resume and our parser extracts publications, methods, and skills to power semantic matching against real award abstracts.',
    },
    {
      icon: Mail,
      title: 'From match to outreach',
      description:
        'Review ranked lab fits, save your pipeline, and draft tailored cold emails grounded in both your narrative and each PI’s funded project.',
    },
  ];

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

    setIsAnalyzing(true);
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
      if (file) {
        formData.append('file', file);
      }

      // Trigger single-pass multipart analysis
      const analyzeResp = await api.post('/profile/analyze', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      const analyzeData = analyzeResp.data;
      if (analyzeData.status !== 'success' && analyzeData.status !== 'partial_success') {
        throw new Error(analyzeData.message || 'Profile synthesis failed.');
      }

      const studentId = analyzeData.student.id || analyzeData.student.auth_id;
      if (!studentId || studentId === 'undefined') {
        throw new Error('Failed to retrieve a valid student ID from profile analysis.');
      }
      
      // Fetch matched research grants
      const matchResp = await api.get(`/grants/matches?student_id=${studentId}&threshold=0.2&limit=5`);
      const matchedGrants = matchResp.data;

      onComplete({
        resumeName: file ? file.name : 'No Resume Provided',
        researchInterests: researchInterests,
        matches: matchedGrants,
        studentId: studentId,
        studentName: name,
      });
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.response?.data?.detail || err.message || 'Communication with the matching engine failed.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <div className="w-full px-4 sm:px-6 py-6 md:py-8 animate-fade-in">
      {/* Title block */}
      <div className="text-center mb-8 md:mb-10 max-w-2xl mx-auto shrink-0">
        <h1 className="text-3xl sm:text-4xl md:text-[2.75rem] font-semibold tracking-tight text-stone-900 font-outfit mb-4 leading-[1.15]">
          Build Your Research Profile
        </h1>
        <p className="text-stone-600 text-base md:text-lg leading-relaxed">
          Upload your academic credentials and detail your research interests to align immediately with active, fully-funded NIH & NSF labs.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="w-full max-w-2xl mx-auto"
      >
        <GlassCard
          className="relative flex flex-col w-full min-h-[28rem] p-6 md:p-8"
          glowColor={uploadStatus === 'success' ? 'teal' : 'none'}
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
              <h2 className="text-xl font-semibold font-outfit text-stone-900 mb-1.5">
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
                    className="shrink-0 px-2.5 py-1 rounded-md text-xs font-semibold text-stone-600 hover:text-stone-900 hover:bg-white border border-transparent hover:border-stone-200 transition-colors"
                  >
                    Replace
                  </button>
                </div>
              )}
            </div>

            <div className="flex flex-col flex-1 min-h-0 gap-4">
              <div className="shrink-0 flex flex-col sm:flex-row gap-3 sm:gap-4">
                <input
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Full Name"
                  className="input-field"
                  required
                />
                <input
                  type="email"
                  value={emailAddress}
                  onChange={(e) => setEmailAddress(e.target.value)}
                  placeholder="Email Address"
                  className="input-field"
                  required
                />
              </div>

              <textarea
                value={researchInterests}
                onChange={(e) => setResearchInterests(e.target.value)}
                placeholder="Example: I am deeply interested in studying neurodegenerative diseases. Specifically, leveraging high-content screening systems and deep learning algorithms to predict cellular drug target engagement..."
                className="input-field flex-1 min-h-[10rem] resize-none leading-relaxed"
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
                      className="chip-suggestion"
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
              className="btn-primary w-full sm:w-auto"
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
        </GlassCard>
      </form>

      <section
        className="w-full max-w-5xl mx-auto mt-16 md:mt-24 pb-8 md:pb-12"
        aria-labelledby="why-labmatch-heading"
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 md:gap-x-6 md:gap-y-5">
          <h2
            id="why-labmatch-heading"
            className="text-left text-xl sm:text-2xl md:text-3xl font-semibold font-outfit text-stone-900 tracking-tight whitespace-nowrap md:col-start-1 md:row-start-1"
          >
            Why people use LabMatch AI
          </h2>
          {whyUseBlocks.map(({ icon: Icon, title, description }, index) => (
            <GlassCard
              key={title}
              className={`p-5 md:p-6 h-full md:row-start-2 ${
                index === 0 ? 'md:col-start-1' : index === 1 ? 'md:col-start-2' : 'md:col-start-3'
              }`}
              glowColor="none"
            >
              <div className="flex items-center gap-3 mb-3">
                <div className="w-10 h-10 shrink-0 rounded-lg bg-[#e8eef1] border border-stone-200 flex items-center justify-center">
                  <Icon className="w-5 h-5 text-[#1e3a4a]" strokeWidth={1.75} />
                </div>
                <h3 className="text-base font-semibold font-outfit text-stone-900 leading-snug min-w-0">
                  {title}
                </h3>
              </div>
              <p className="text-stone-600 text-sm leading-relaxed">
                {description}
              </p>
            </GlassCard>
          ))}
        </div>
      </section>
    </div>
  );
};

export default Onboarding;
