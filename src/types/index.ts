export type TransportMode = "walking" | "driving" | "transit" | "cycling";

export interface TripRequest {
  location: string;
  budget: number;
  transport: TransportMode;
  durationHours: number;
  vibe: string;
  constraints?: string;
}

export interface Stop {
  time: string;
  name: string;
  description: string;
  address?: string;
  estimatedCost?: number;
  travelTimeToNext?: string;
  lat?: number;
  lng?: number;
}

export interface Itinerary {
  tripId: string;
  summary: string;
  stops: Stop[];
  totalEstimatedCost: number;
  warnings: string[];
}
