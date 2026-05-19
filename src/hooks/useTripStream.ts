import { useState, useCallback } from "react";
import { streamTripPlan } from "@/lib/api";
import type { TripRequest } from "@/types";

interface UseTripStreamResult {
  output: string;
  isStreaming: boolean;
  error: string | null;
  startStream: (request: TripRequest) => Promise<void>;
}

export function useTripStream(): UseTripStreamResult {
  const [output, setOutput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startStream = useCallback(async (request: TripRequest) => {
    setOutput("");
    setError(null);
    setIsStreaming(true);

    try {
      const stream = await streamTripPlan(request);
      const reader = stream.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        setOutput((prev) => prev + chunk);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setIsStreaming(false);
    }
  }, []);

  return { output, isStreaming, error, startStream };
}
