"use client";

import { useMapbox } from "@/hooks/useMapbox";
import type { Stop } from "@/types";

interface ItineraryMapProps {
  stops: Stop[];
}

export function ItineraryMap({ stops }: ItineraryMapProps) {
  const { mapContainer } = useMapbox({ stops });

  return (
    <div
      ref={mapContainer}
      className="w-full h-72 rounded-xl border overflow-hidden bg-gray-100"
    />
  );
}
