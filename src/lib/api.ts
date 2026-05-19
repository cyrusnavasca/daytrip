import type { TripRequest } from "@/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

/**
 * Opens an SSE stream to the FastAPI /plan endpoint.
 * The caller is responsible for reading from the ReadableStream.
 */
export async function streamTripPlan(request: TripRequest): Promise<ReadableStream<Uint8Array>> {
  const response = await fetch(`${BACKEND_URL}/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      location: request.location,
      budget: request.budget,
      transport: request.transport,
      duration_hours: request.durationHours,
      vibe: request.vibe,
      constraints: request.constraints,
    }),
  });

  if (!response.ok) {
    throw new Error(`Backend error: ${response.status}`);
  }

  if (!response.body) {
    throw new Error("No response body from backend");
  }

  return response.body;
}
