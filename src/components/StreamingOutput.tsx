"use client";

interface StreamingOutputProps {
  text: string;
  isStreaming: boolean;
}

export function StreamingOutput({ text, isStreaming }: StreamingOutputProps) {
  if (!text && !isStreaming) return null;

  return (
    <div className="w-full max-w-2xl rounded-xl border bg-gray-50 p-4 font-mono text-sm text-gray-800 whitespace-pre-wrap">
      {text}
      {isStreaming && <span className="animate-pulse">▌</span>}
    </div>
  );
}
