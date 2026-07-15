"use client";

import React, { useState, useEffect, useRef } from "react";
import { UploadCloud, AlertCircle, File, HelpCircle, CheckCircle2, RefreshCw, Plus, Loader2, XCircle } from "lucide-react";
import { useKnowledgeBase } from "@/context/KnowledgeBaseContext";
import { DocumentsService, DocumentItem } from "@/services/documents";
import Link from "next/link";

export default function UploadPage() {
  const { 
    knowledgeBases: kbs, 
    selectedKbId, 
    selectedKb, 
    setSelectedKbId, 
    isLoading: loadingKbs, 
    refreshKnowledgeBases,
    createKnowledgeBase
  } = useKnowledgeBase();

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState<boolean>(false);
  const [progress, setProgress] = useState<number>(0);
  const [success, setSuccess] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragActive, setIsDragActive] = useState<boolean>(false);
  const [processingDoc, setProcessingDoc] = useState<DocumentItem | null>(null);
  const [pollingActive, setPollingActive] = useState<boolean>(false);
  const delayRef = useRef<number>(2000);
  const [timestamps, setTimestamps] = useState<Record<string, string>>({});

  // Quick Create States
  const [showQuickCreate, setShowQuickCreate] = useState<boolean>(false);
  const [quickKbName, setQuickKbName] = useState<string>("");
  const [creatingQuickKb, setCreatingQuickKb] = useState<boolean>(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Polling for uploaded file processing status using recursive setTimeout
  useEffect(() => {
    if (!pollingActive || !processingDoc) return;

    const docId = processingDoc.id;
    let timer: NodeJS.Timeout;

    // Reset backoff delay at starting point
    delayRef.current = 2000;

    async function checkStatus() {
      try {
        const docs = await DocumentsService.getDocuments();
        const found = docs.find((d) => d.id === docId);
        
        if (found) {
          setProcessingDoc(found);

          // Record client-side timestamps for transitions
          setTimestamps((prev) => {
            const updated = { ...prev };
            const now = new Date().toLocaleTimeString();
            if (found.status === "Uploaded" && !updated.Uploaded) {
              updated.Uploaded = now;
            }
            if (found.status === "Parsing" && !updated.Parsing) {
              updated.Parsing = now;
              if (!updated.Uploaded) updated.Uploaded = now;
            }
            if (found.status === "Parsed" && !updated.Parsed) {
              updated.Parsed = now;
              if (!updated.Uploaded) updated.Uploaded = now;
              if (!updated.Parsing) updated.Parsing = now;
            }
            if (found.status === "Failed" && !updated.Failed) {
              updated.Failed = now;
            }
            return updated;
          });

          if (found.status === "Parsed" || found.status === "Failed") {
            setPollingActive(false);
            refreshKnowledgeBases();
            return;
          }
        }
        
        // Exponential backoff logic: 2s -> 3.5s -> 5s -> 6.5s -> 8s -> 9.5s -> 10s max
        delayRef.current = Math.min(delayRef.current + 1500, 10000);
        timer = setTimeout(checkStatus, delayRef.current);
      } catch (err) {
        console.error("Failed to check doc status:", err);
        delayRef.current = Math.min(delayRef.current + 2000, 10000);
        timer = setTimeout(checkStatus, delayRef.current);
      }
    }

    timer = setTimeout(checkStatus, delayRef.current);
    return () => clearTimeout(timer);
  }, [pollingActive, processingDoc?.id]);

  const handleQuickCreateKb = async () => {
    if (!quickKbName.trim()) return;
    setCreatingQuickKb(true);
    setError(null);
    try {
      await createKnowledgeBase(quickKbName);
      setShowQuickCreate(false);
      setQuickKbName("");
    } catch (err: any) {
      console.error("Failed to create KB from upload page", err);
      setError(err.message || "Failed to create Knowledge Base. Please try again.");
    } finally {
      setCreatingQuickKb(false);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setIsDragActive(true);
    } else if (e.type === "dragleave") {
      setIsDragActive(false);
    }
  };

  const validateAndSetFile = (file: File) => {
    setError(null);
    setSuccess(false);

    // Validate size (50MB)
    const maxSize = 50 * 1024 * 1024;
    if (file.size > maxSize) {
      setError("File size exceeds 50 MB limit.");
      return;
    }

    // Validate extension
    const allowedExtensions = [".pdf", ".docx", ".txt", ".md", ".markdown"];
    const fileExtension = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
    if (!allowedExtensions.includes(fileExtension)) {
      setError(`Unsupported file extension. Allowed extensions: ${allowedExtensions.join(", ")}`);
      return;
    }

    setSelectedFile(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const triggerFileBrowser = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile || !selectedKb) return;

    setUploading(true);
    setProgress(0);
    setError(null);
    setSuccess(false);
    setProcessingDoc(null);
    setTimestamps({});

    try {
      const doc = await DocumentsService.uploadDocument(selectedFile, selectedKb.uuid, (percent) => {
        setProgress(percent);
      });
      const nowStr = new Date().toLocaleTimeString();
      setSuccess(true);
      setProcessingDoc(doc);
      setPollingActive(true);
      setTimestamps({ Uploaded: nowStr });
      setSelectedFile(null);
    } catch (err: any) {
      console.error("Upload error", err);
      let friendlyMessage = "Failed to upload document. Please ensure the backend server is reachable.";
      if (err.response) {
        if (err.response.status === 409) {
          friendlyMessage = "This document already exists in the selected Knowledge Base. Duplicates are not allowed.";
        } else if (err.response.status === 413) {
          friendlyMessage = "The uploaded file exceeds the maximum size limit of 50 MB.";
        } else if (err.response.status === 404) {
          friendlyMessage = "The destination Knowledge Base was not found on the server.";
        } else if (err.response.data?.detail) {
          friendlyMessage = typeof err.response.data.detail === "string" ? err.response.data.detail : JSON.stringify(err.response.data.detail);
        }
      }
      setError(friendlyMessage);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-in fade-in duration-300">
      {/* Title */}
      <div>
        <h1 className="text-xl font-bold tracking-tight text-foreground">Upload Knowledge</h1>
        <p className="text-xs text-muted-foreground mt-1">
          Upload corporate documents to index them into your security-isolated knowledge bases.
        </p>
      </div>

      {/* Upload card container */}
      <div className="rounded-xl border border-border bg-card p-6 shadow-sm space-y-6">
        
        {/* Knowledge Base selector */}
        <div className="space-y-2">
          <label className="text-xs font-bold text-foreground uppercase tracking-wider block">
            Select Destination Knowledge Base
          </label>
          {loadingKbs ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
              <RefreshCw className="h-3 w-3 animate-spin" />
              <span>Loading your knowledge bases...</span>
            </div>
          ) : kbs.length === 0 ? (
            <div className="rounded-lg border border-warning/20 bg-warning/10 p-3 text-xs text-warning flex flex-col gap-3">
              <div className="flex items-start gap-2.5">
                <AlertCircle className="h-4.5 w-4.5 shrink-0 mt-0.5" />
                <div>
                  <p className="font-bold">No active Knowledge Bases found</p>
                  <p className="opacity-90 mt-0.5">
                    You need to create a Knowledge Base first before uploading files.{" "}
                    <Link href="/documents" className="underline font-bold hover:opacity-85">
                      Go to folders &rarr;
                    </Link>
                  </p>
                </div>
              </div>
              
              {!showQuickCreate ? (
                <div>
                  <button
                    type="button"
                    onClick={() => setShowQuickCreate(true)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-[11px] font-bold shadow-xs transition-all w-fit cursor-pointer"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    <span>Create Knowledge Base</span>
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2 border-t border-warning/20 pt-2.5 w-full max-w-md animate-in fade-in duration-200">
                  <input
                    type="text"
                    placeholder="Enter Knowledge Base Name..."
                    value={quickKbName}
                    onChange={(e) => setQuickKbName(e.target.value)}
                    disabled={creatingQuickKb}
                    className="flex-1 bg-background border border-border rounded-lg px-3 py-1.5 text-xs text-foreground focus:outline-hidden"
                  />
                  <button
                    type="button"
                    onClick={handleQuickCreateKb}
                    disabled={creatingQuickKb || !quickKbName.trim()}
                    className="px-3 py-1.5 bg-primary text-primary-foreground hover:bg-primary/95 text-xs font-bold rounded-lg transition-all cursor-pointer disabled:opacity-40"
                  >
                    {creatingQuickKb ? "Creating..." : "Create"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowQuickCreate(false);
                      setQuickKbName("");
                    }}
                    disabled={creatingQuickKb}
                    className="px-3 py-1.5 border border-border bg-card text-foreground hover:bg-accent text-xs font-bold rounded-lg transition-all cursor-pointer"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          ) : (
            <select
              value={selectedKbId || ""}
              onChange={(e) => setSelectedKbId(Number(e.target.value))}
              disabled={uploading}
              className="w-full bg-slate-900 border border-border rounded-lg px-3 py-2 text-xs text-foreground focus:outline-hidden focus:ring-1 focus:ring-primary shadow-inner"
            >
              {kbs.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name} (Created {kb.date})
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Drag and Drop area */}
        {kbs.length > 0 && (
          <div
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={triggerFileBrowser}
            className={`rounded-xl border-2 border-dashed p-8 flex flex-col items-center justify-center min-h-[220px] transition-all duration-300 cursor-pointer relative overflow-hidden ${
              isDragActive
                ? "border-primary bg-primary/5 scale-[0.99] shadow-md shadow-primary/5"
                : "border-border hover:border-primary/60 hover:bg-slate-50/5 dark:hover:bg-zinc-900/10"
            }`}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileInputChange}
              disabled={uploading}
              className="hidden"
              accept=".pdf,.docx,.txt,.md,.markdown"
            />

            <div className="flex flex-col items-center justify-center text-center gap-3 max-w-sm z-10 pointer-events-none select-none">
              <div className={`flex h-12 w-12 items-center justify-center rounded-full transition-colors ${
                isDragActive ? "bg-primary text-primary-foreground" : "bg-slate-100 dark:bg-zinc-800 text-slate-400 dark:text-zinc-500"
              }`}>
                <UploadCloud className="h-6 w-6" />
              </div>
              
              <div className="space-y-1">
                <h3 className="text-xs font-bold text-foreground">
                  {selectedFile ? "Selected: " + selectedFile.name : "Drag and drop document here"}
                </h3>
                <p className="text-[10px] text-muted-foreground">
                  {selectedFile 
                    ? `Size: ${(selectedFile.size / (1024 * 1024)).toFixed(2)} MB`
                    : "Or click to browse your file system"}
                </p>
              </div>

              {!selectedFile && (
                <div className="flex flex-wrap items-center justify-center gap-1.5 mt-1">
                  {["PDF", "DOCX", "TXT", "MD"].map((ext) => (
                    <span key={ext} className="inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold uppercase bg-muted text-muted-foreground border border-border/80">
                      {ext}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Upload status / controls */}
        {selectedFile && !uploading && !success && (
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              onClick={() => setSelectedFile(null)}
              className="px-3.5 py-1.5 text-xs font-semibold rounded-lg hover:bg-muted text-muted-foreground transition-all"
            >
              Cancel
            </button>
            <button
              onClick={handleUpload}
              className="px-4 py-1.5 text-xs font-bold bg-primary text-primary-foreground hover:bg-primary/95 transition-all shadow-md shadow-primary/10 rounded-lg"
            >
              Upload Document
            </button>
          </div>
        )}

        {/* Upload progress indicator */}
        {uploading && (
          <div className="space-y-2 pt-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div className="flex justify-between items-center text-xs">
              <span className="font-bold text-foreground flex items-center gap-1.5">
                <RefreshCw className="h-3.5 w-3.5 animate-spin text-primary" />
                {progress === 100 ? "Processing Document..." : "Uploading document..."}
              </span>
              <span className="font-mono text-muted-foreground font-semibold">{progress}%</span>
            </div>
            <div className="h-1.5 w-full bg-slate-100 dark:bg-zinc-800 rounded-full overflow-hidden">
              <div 
                className="h-full bg-primary rounded-full transition-all duration-300 ease-out" 
                style={{ width: `${progress}%` }}
              ></div>
            </div>
          </div>
        )}

        {/* Ingestion Pipeline status tracker */}
        {success && processingDoc && (
          <div className="rounded-xl border border-border/80 bg-card p-5 space-y-5 animate-in zoom-in-95 duration-300 shadow-xs">
            {/* Header info */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pb-3 border-b border-border/40">
              <div className="space-y-1">
                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider block">Ingestion Pipeline</span>
                <span className="text-xs font-bold text-foreground truncate block max-w-sm">{processingDoc.name} ({processingDoc.size})</span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`px-2.5 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider ${
                  processingDoc.status === "Parsed"
                    ? "bg-emerald-500/10 text-emerald-500 border border-emerald-500/10"
                    : processingDoc.status === "Failed"
                    ? "bg-rose-500/10 text-rose-500 border border-rose-500/10"
                    : "bg-amber-500/10 text-amber-500 border border-amber-500/10 animate-pulse"
                }`}>
                  {processingDoc.status}
                </span>
              </div>
            </div>

            {/* Pipeline Step Indicators */}
            <div className="space-y-3">
              {/* Step 1: Upload Complete */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4.5 w-4.5 text-emerald-500 shrink-0" />
                  <span className="font-semibold text-foreground">Upload Complete</span>
                </div>
                <div className="flex items-center gap-2">
                  {timestamps.Uploaded && (
                    <span className="font-mono text-[9px] text-muted-foreground mr-1.5">{timestamps.Uploaded}</span>
                  )}
                  <span className="text-[10px] font-bold text-emerald-500 bg-emerald-500/10 px-2 py-0.5 rounded-md border border-emerald-500/10">100%</span>
                </div>
              </div>

              {/* Step 1: Uploading */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4.5 w-4.5 text-emerald-500 shrink-0" />
                  <span className="font-semibold text-foreground">Uploading</span>
                </div>
                <div className="flex items-center gap-2 font-mono text-[9px] text-muted-foreground">
                  <span className="text-[10px] font-bold text-emerald-500 bg-emerald-500/10 px-2 py-0.5 rounded-md border border-emerald-500/10">100%</span>
                </div>
              </div>

              {/* Step 2: Parsing */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  {processingDoc.status === "Parsing" ? (
                    <RefreshCw className="h-4.5 w-4.5 text-amber-500 animate-spin shrink-0" />
                  ) : processingDoc.status === "Parsed" ? (
                    <CheckCircle2 className="h-4.5 w-4.5 text-emerald-500 shrink-0" />
                  ) : processingDoc.status === "Failed" ? (
                    <XCircle className="h-4.5 w-4.5 text-rose-500 shrink-0" />
                  ) : (
                    <div className="h-4.5 w-4.5 rounded-full border border-border/80 shrink-0" />
                  )}
                  <span className={`font-semibold ${
                    processingDoc.status === "Parsing" ? "text-amber-500 animate-pulse" : processingDoc.status === "Parsed" ? "text-foreground" : "text-muted-foreground/60"
                  }`}>
                    Parsing
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-bold ${
                    processingDoc.status === "Parsing" ? "text-amber-500" : processingDoc.status === "Parsed" ? "text-emerald-500" : "text-muted-foreground/45"
                  }`}>
                    {processingDoc.status === "Parsing" ? "Parsing..." : processingDoc.status === "Parsed" ? "Completed" : "Pending"}
                  </span>
                </div>
              </div>

              {/* Step 3: Chunking */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  {processingDoc.status === "Parsing" ? (
                    <RefreshCw className="h-4.5 w-4.5 text-amber-500 animate-spin shrink-0" />
                  ) : processingDoc.status === "Parsed" ? (
                    <CheckCircle2 className="h-4.5 w-4.5 text-emerald-500 shrink-0" />
                  ) : (
                    <div className="h-4.5 w-4.5 rounded-full border border-border/80 shrink-0" />
                  )}
                  <span className={`font-semibold ${
                    processingDoc.status === "Parsing" ? "text-amber-500" : processingDoc.status === "Parsed" ? "text-foreground" : "text-muted-foreground/60"
                  }`}>
                    Chunking
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-bold ${
                    processingDoc.status === "Parsing" ? "text-amber-500" : processingDoc.status === "Parsed" ? "text-emerald-500" : "text-muted-foreground/45"
                  }`}>
                    {processingDoc.status === "Parsing" ? "Generating..." : processingDoc.status === "Parsed" ? `Created ${processingDoc.chunks} chunks` : "Pending"}
                  </span>
                </div>
              </div>

              {/* Step 4: Embedding */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  {processingDoc.status === "Parsing" ? (
                    <RefreshCw className="h-4.5 w-4.5 text-amber-500 animate-spin shrink-0" />
                  ) : processingDoc.status === "Parsed" ? (
                    <CheckCircle2 className="h-4.5 w-4.5 text-emerald-500 shrink-0" />
                  ) : (
                    <div className="h-4.5 w-4.5 rounded-full border border-border/80 shrink-0" />
                  )}
                  <span className={`font-semibold ${
                    processingDoc.status === "Parsing" ? "text-amber-500" : processingDoc.status === "Parsed" ? "text-foreground" : "text-muted-foreground/60"
                  }`}>
                    Embedding
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-bold ${
                    processingDoc.status === "Parsing" ? "text-amber-500" : processingDoc.status === "Parsed" ? "text-emerald-500" : "text-muted-foreground/45"
                  }`}>
                    {processingDoc.status === "Parsing" ? "Embedding..." : processingDoc.status === "Parsed" ? "Completed" : "Pending"}
                  </span>
                </div>
              </div>

              {/* Step 5: Indexing */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  {processingDoc.status === "Parsing" ? (
                    <RefreshCw className="h-4.5 w-4.5 text-amber-500 animate-spin shrink-0" />
                  ) : processingDoc.status === "Parsed" ? (
                    <CheckCircle2 className="h-4.5 w-4.5 text-emerald-500 shrink-0" />
                  ) : (
                    <div className="h-4.5 w-4.5 rounded-full border border-border/80 shrink-0" />
                  )}
                  <span className={`font-semibold ${
                    processingDoc.status === "Parsing" ? "text-amber-500" : processingDoc.status === "Parsed" ? "text-foreground" : "text-muted-foreground/60"
                  }`}>
                    Indexing
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-bold ${
                    processingDoc.status === "Parsing" ? "text-amber-500" : processingDoc.status === "Parsed" ? "text-emerald-500" : "text-muted-foreground/45"
                  }`}>
                    {processingDoc.status === "Parsing" ? "Indexing..." : processingDoc.status === "Parsed" ? "Completed" : "Pending"}
                  </span>
                </div>
              </div>

              {/* Step 6: Completed */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  {processingDoc.status === "Parsed" ? (
                    <CheckCircle2 className="h-4.5 w-4.5 text-emerald-500 shrink-0" />
                  ) : processingDoc.status === "Failed" ? (
                    <XCircle className="h-4.5 w-4.5 text-rose-500 shrink-0" />
                  ) : (
                    <div className="h-4.5 w-4.5 rounded-full border border-border/80 shrink-0" />
                  )}
                  <span className={`font-semibold ${
                    processingDoc.status === "Parsed" ? "text-emerald-500 font-bold" : "text-muted-foreground/60"
                  }`}>
                    Completed
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-bold ${
                    processingDoc.status === "Parsed" ? "text-emerald-500" : processingDoc.status === "Failed" ? "text-rose-500" : "text-muted-foreground/45"
                  }`}>
                    {processingDoc.status === "Parsed" ? "Ready" : processingDoc.status === "Failed" ? "Failed" : "Pending"}
                  </span>
                </div>
              </div>
            </div>

            {/* Success details / metadata box */}
            {processingDoc.status === "Parsed" && (
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-3.5 space-y-3 text-emerald-500 animate-in zoom-in-95 duration-200">
                <div className="flex items-center gap-2 text-xs font-bold">
                  <CheckCircle2 className="h-4.5 w-4.5 shrink-0" />
                  <span>Document processed successfully. Ready for AI Search.</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 text-[10px] font-semibold border-t border-emerald-500/10 pt-3">
                  <div>Parser: <span className="font-bold text-foreground bg-emerald-500/5 px-1.5 py-0.5 rounded-md border border-emerald-500/10 ml-0.5">{processingDoc.parserName || "TXT Parser"}</span></div>
                  <div>Language: <span className="font-bold text-foreground bg-emerald-500/5 px-1.5 py-0.5 rounded-md border border-emerald-500/10 ml-0.5">{processingDoc.lang}</span></div>
                  <div>Pages: <span className="font-bold text-foreground bg-emerald-500/5 px-1.5 py-0.5 rounded-md border border-emerald-500/10 ml-0.5">{processingDoc.pages ?? "—"}</span></div>
                  <div>Characters: <span className="font-bold text-foreground bg-emerald-500/5 px-1.5 py-0.5 rounded-md border border-emerald-500/10 ml-0.5">{processingDoc.characters ?? "—"}</span></div>
                  <div>Chunks: <span className="font-bold text-foreground bg-emerald-500/5 px-1.5 py-0.5 rounded-md border border-emerald-500/10 ml-0.5">{processingDoc.chunks}</span></div>
                  <div>Time: <span className="font-bold text-foreground bg-emerald-500/5 px-1.5 py-0.5 rounded-md border border-emerald-500/10 ml-0.5">{processingDoc.processingTime ?? "0.00"}s</span></div>
                </div>
                <div className="pt-2 text-right">
                  <Link href="/documents" className="text-xs font-bold underline hover:opacity-85 inline-flex items-center gap-1">
                    Manage Files in Folders &rarr;
                  </Link>
                </div>
              </div>
            )}

            {/* Failure Box */}
            {processingDoc.status === "Failed" && (
              <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-3.5 space-y-3 text-rose-500 animate-in shake duration-300">
                <div className="flex items-center gap-2 text-xs font-bold">
                  <XCircle className="h-4.5 w-4.5 shrink-0" />
                  <span>Processing Failed</span>
                </div>
                <div className="text-[10px] font-semibold">
                  Reason: <span className="font-bold text-foreground ml-0.5">{processingDoc.errorDetail || "An unexpected error occurred during processing."}</span>
                </div>
                <div className="flex items-center gap-3 pt-2">
                  <button
                    onClick={() => {
                      setSelectedFile(null);
                      setProcessingDoc(null);
                      setSuccess(false);
                      setProgress(0);
                    }}
                    className="px-3.5 py-1.5 bg-rose-500 hover:bg-rose-600 text-white text-[10px] font-bold rounded-lg transition-all cursor-pointer border border-transparent shadow-md"
                  >
                    Retry Upload
                  </button>
                  <Link href="/documents" className="text-xs font-bold underline hover:opacity-85 inline-flex items-center gap-1 ml-auto">
                    View Folders &rarr;
                  </Link>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Error Alert */}
        {error && (
          <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-destructive flex items-start gap-3 animate-in shake duration-300">
            <AlertCircle className="h-5 w-5 shrink-0" />
            <div className="space-y-1">
              <h4 className="text-xs font-bold">Upload Failed</h4>
              <p className="text-[11px] opacity-90 leading-relaxed font-semibold">
                {error}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Guide Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 pt-2">
        <div className="rounded-xl border border-border bg-card p-5 flex gap-3 text-left">
          <File className="h-5 w-5 text-primary shrink-0 mt-0.5" />
          <div className="space-y-1">
            <h4 className="text-xs font-bold text-foreground">Anti-Virus Ingestion Pipeline</h4>
            <p className="text-[10px] text-muted-foreground leading-relaxed">
              Files are securely saved to sandbox storage, checked for viruses, and verified with SHA-256 hashes to guarantee data integrity.
            </p>
          </div>
        </div>
        
        <div className="rounded-xl border border-border bg-card p-5 flex gap-3 text-left">
          <HelpCircle className="h-5 w-5 text-primary shrink-0 mt-0.5" />
          <div className="space-y-1">
            <h4 className="text-xs font-bold text-foreground">Supported File Specifications</h4>
            <p className="text-[10px] text-muted-foreground leading-relaxed">
              Max file upload limit is 50 MB. Supported file extensions include: .pdf, .docx, .txt, .md, .markdown.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}