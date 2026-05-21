import React, { useState, useRef } from 'react';
import { Upload, FileText, CheckCircle2, AlertCircle, Sparkles, ChevronRight, RefreshCw } from 'lucide-react';
import GlassCard from '../components/GlassCard';

interface OnboardingProps {
  onComplete: (data: { resumeName: string; researchInterests: string }) => void;
}

export const Onboarding: React.FC<OnboardingProps> = ({ onComplete }) => {
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [researchInterests, setResearchInterests] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Suggested keywords to prompt student typing
  const interestPrompts = [
    "CRISPR-Cas9 gene editing",
    "Deep learning for protein folding",
    "Microfluidic organ-on-a-chip",
    "Somatic mutations in glioma",
    "Single-cell RNA-sequencing"
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

  const simulateUpload = (selectedFile: File) => {
    if (selectedFile.type !== 'application/pdf') {
      setErrorMsg('Please upload a PDF file only.');
      setUploadStatus('error');
      return;
    }

    setFile(selectedFile);
    setUploadStatus('loading');
    setUploadProgress(0);
    setErrorMsg('');

    // Simulate upload progress
    const interval = setInterval(() => {
      setUploadProgress((prev) => {
        if (prev >= 100) {
          clearInterval(interval);
          setUploadStatus('success');
          return 100;
        }
        return prev + 10;
      });
    }, 120);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      simulateUpload(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      simulateUpload(e.target.files[0]);
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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setErrorMsg('A professional CV or Resume (PDF) is required to parse competencies.');
      setUploadStatus('error');
      return;
    }
    if (!researchInterests.trim()) {
      setErrorMsg('Please detail your research interests or project ideas.');
      return;
    }

    onComplete({
      resumeName: file.name,
      researchInterests: researchInterests,
    });
  };

  return (
    <div className="w-full max-w-6xl mx-auto px-4 py-8 animate-fade-in">
      {/* Title block */}
      <div className="text-center mb-10">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-teal-500/10 border border-teal-500/30 text-teal-400 text-sm font-semibold mb-3">
          <Sparkles className="w-4 h-4" /> Synthesized Profile Matching
        </div>
        <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight text-white font-outfit mb-3">
          Build Your Research Profile
        </h1>
        <p className="text-slate-400 text-lg max-w-2xl mx-auto font-light leading-relaxed">
          Upload your academic credentials and detail your research interests to align immediately with active, fully-funded NIH & NSF labs.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
        {/* Left side - Resume PDF upload */}
        <GlassCard className="relative overflow-hidden group min-h-[420px] flex flex-col justify-between" glowColor={uploadStatus === 'success' ? 'teal' : 'none'}>
          {/* Subtle neon accents */}
          <div className="absolute top-0 left-0 w-full h-[3px] bg-gradient-to-r from-transparent via-teal-500/50 to-transparent" />
          
          <div>
            <h2 className="text-2xl font-bold font-outfit text-white mb-2 flex items-center gap-2">
              <FileText className="w-6 h-6 text-teal-400" /> Academic CV / Resume
            </h2>
            <p className="text-slate-400 text-sm font-light mb-6">
              Our background NLP parser will extract your publications, technical skills, and research background.
            </p>

            {uploadStatus === 'idle' || uploadStatus === 'error' ? (
              <div
                onDragEnter={handleDrag}
                onDragOver={handleDrag}
                onDragLeave={handleDrag}
                onDrop={handleDrop}
                onClick={triggerFileSelect}
                className={`
                  border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center cursor-pointer transition-all duration-300 min-h-[220px]
                  ${dragActive ? 'border-teal-400 bg-teal-500/10 shadow-[0_0_20px_0_rgba(45,212,191,0.1)]' : 'border-slate-700/60 hover:border-teal-500/40 hover:bg-slate-800/20'}
                `}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  className="hidden"
                  onChange={handleFileChange}
                />
                <div className="w-12 h-12 rounded-full bg-slate-800/80 flex items-center justify-center mb-4 group-hover:scale-110 transition-transform duration-300">
                  <Upload className="w-6 h-6 text-slate-400 group-hover:text-teal-400 transition-colors" />
                </div>
                <p className="text-white font-medium text-center mb-1">
                  Drag & drop your Resume or CV PDF here
                </p>
                <p className="text-slate-400 text-xs text-center font-light">
                  Supports PDF files up to 10MB
                </p>
              </div>
            ) : uploadStatus === 'loading' ? (
              <div className="border border-slate-800/80 bg-slate-900/40 rounded-xl p-8 flex flex-col items-center justify-center min-h-[220px]">
                <RefreshCw className="w-10 h-10 text-teal-400 animate-spin mb-4" />
                <p className="text-white font-medium mb-2">Analyzing Resume & Extracting Core Competencies...</p>
                <div className="w-full max-w-xs bg-slate-800 h-2 rounded-full overflow-hidden">
                  <div 
                    className="bg-teal-400 h-full rounded-full transition-all duration-300"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
                <span className="text-teal-400 font-semibold text-xs mt-2">{uploadProgress}% Complete</span>
              </div>
            ) : (
              <div className="border border-teal-500/30 bg-teal-950/20 rounded-xl p-8 flex flex-col items-center justify-center min-h-[220px] relative">
                <CheckCircle2 className="w-12 h-12 text-teal-400 mb-3" />
                <h3 className="text-white font-semibold text-center mb-1">CV Successfully Extracted!</h3>
                <p className="text-slate-300 text-sm font-mono bg-slate-900/80 px-4 py-1.5 rounded-lg border border-slate-800 flex items-center gap-2 max-w-xs truncate mb-4">
                  <FileText className="w-4 h-4 text-teal-400 shrink-0" />
                  {file?.name}
                </p>
                <button
                  type="button"
                  onClick={resetUpload}
                  className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors border border-slate-700 flex items-center gap-1.5"
                >
                  <RefreshCw className="w-3.5 h-3.5" /> Replace Resume
                </button>
              </div>
            )}
          </div>

          {/* Bottom error rendering */}
          {errorMsg && (
            <div className="mt-4 p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 text-sm flex items-start gap-2.5">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}
        </GlassCard>

        {/* Right side - Research Interests & Prompting suggestions */}
        <GlassCard className="relative overflow-hidden group min-h-[420px] flex flex-col justify-between" glowColor="none">
          {/* Subtle neon accents */}
          <div className="absolute top-0 left-0 w-full h-[3px] bg-gradient-to-r from-transparent via-purple-500/50 to-transparent" />

          <div>
            <h2 className="text-2xl font-bold font-outfit text-white mb-2 flex items-center gap-2">
              <Sparkles className="w-6 h-6 text-purple-400" /> Research Narrative & Goals
            </h2>
            <p className="text-slate-400 text-sm font-light mb-6">
              Describe your scientific goals, methodologies, or specific problems you wish to investigate.
            </p>

            <div className="space-y-4">
              <textarea
                value={researchInterests}
                onChange={(e) => setResearchInterests(e.target.value)}
                placeholder="Example: I am deeply interested in studying neurodegenerative diseases. Specifically, leveraging high-content screening systems and deep learning algorithms to predict cellular drug target engagement..."
                className="w-full h-44 rounded-xl bg-slate-900/60 border border-slate-700/60 focus:border-purple-500/70 p-4 text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-purple-500/50 resize-none font-light leading-relaxed text-sm"
              />

              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2.5">
                  Suggested Research Vectors (Click to append)
                </p>
                <div className="flex flex-wrap gap-2">
                  {interestPrompts.map((term, index) => (
                    <button
                      key={index}
                      type="button"
                      onClick={() => appendInterest(term)}
                      className="px-2.5 py-1.5 rounded-lg bg-slate-800/80 hover:bg-purple-950/20 text-slate-300 hover:text-purple-400 border border-slate-700/60 hover:border-purple-500/40 text-xs font-medium transition-all duration-200 cursor-pointer"
                    >
                      + {term}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="mt-8 pt-4 border-t border-slate-800/80 flex justify-end">
            <button
              type="submit"
              className="px-6 py-3 rounded-xl bg-gradient-to-r from-teal-500 to-purple-600 hover:from-teal-400 hover:to-purple-500 text-white font-semibold flex items-center gap-2 shadow-lg shadow-teal-500/10 glow-action transition-all duration-300 text-sm cursor-pointer"
            >
              Analyze & Sync Matches <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </GlassCard>
      </form>
    </div>
  );
};

export default Onboarding;
