import { useEffect, useRef } from "react";
import type { Stop } from "@/types";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN ?? "";

interface UseMapboxOptions {
  stops: Stop[];
}

export function useMapbox({ stops }: UseMapboxOptions) {
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<unknown>(null);

  useEffect(() => {
    // TODO: initialize Mapbox GL map, add markers per stop
    // Depends on mapbox-gl being installed
  }, [stops]);

  return { mapContainer };
}
