import type { Stop } from "@/types";

interface ItineraryCardProps {
  stop: Stop;
  index: number;
}

export function ItineraryCard({ stop, index }: ItineraryCardProps) {
  return (
    <div className="flex gap-4 p-4 rounded-xl border bg-white shadow-sm">
      <div className="flex flex-col items-center gap-1 min-w-[60px]">
        <span className="text-xs font-mono text-gray-500">{stop.time}</span>
        <span className="w-6 h-6 rounded-full bg-black text-white text-xs flex items-center justify-center font-bold">
          {index + 1}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <h3 className="font-semibold text-gray-900">{stop.name}</h3>
        {stop.address && <p className="text-xs text-gray-400">{stop.address}</p>}
        <p className="text-sm text-gray-600">{stop.description}</p>
        {stop.estimatedCost !== undefined && (
          <p className="text-xs text-green-600 font-medium">
            ~${stop.estimatedCost.toFixed(0)}
          </p>
        )}
        {stop.travelTimeToNext && (
          <p className="text-xs text-gray-400 mt-1">→ {stop.travelTimeToNext} to next stop</p>
        )}
      </div>
    </div>
  );
}
