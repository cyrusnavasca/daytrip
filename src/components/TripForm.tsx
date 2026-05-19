"use client";

import { useState } from "react";
import type { TripRequest, TransportMode } from "@/types";

interface TripFormProps {
  onSubmit: (request: TripRequest) => void;
  isLoading: boolean;
}

const TRANSPORT_OPTIONS: { value: TransportMode; label: string }[] = [
  { value: "driving", label: "Driving" },
  { value: "walking", label: "Walking" },
  { value: "transit", label: "Transit" },
  { value: "cycling", label: "Cycling" },
];

export function TripForm({ onSubmit, isLoading }: TripFormProps) {
  const [form, setForm] = useState<TripRequest>({
    location: "",
    budget: 100,
    transport: "driving",
    durationHours: 8,
    vibe: "",
    constraints: "",
  });

  function handleChange(
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) {
    const { name, value } = e.target;
    setForm((prev) => ({
      ...prev,
      [name]: name === "budget" || name === "durationHours" ? Number(value) : value,
    }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit(form);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 w-full max-w-lg">
      <input
        name="location"
        placeholder="Starting location (e.g. Santa Barbara, CA)"
        value={form.location}
        onChange={handleChange}
        required
        className="border rounded-lg px-4 py-2"
      />
      <input
        name="vibe"
        placeholder="Vibe / preferences (e.g. coastal, solo, artsy)"
        value={form.vibe}
        onChange={handleChange}
        required
        className="border rounded-lg px-4 py-2"
      />
      <div className="flex gap-3">
        <input
          name="budget"
          type="number"
          min={0}
          placeholder="Budget ($)"
          value={form.budget}
          onChange={handleChange}
          required
          className="border rounded-lg px-4 py-2 w-1/2"
        />
        <input
          name="durationHours"
          type="number"
          min={1}
          max={24}
          placeholder="Hours"
          value={form.durationHours}
          onChange={handleChange}
          required
          className="border rounded-lg px-4 py-2 w-1/2"
        />
      </div>
      <select
        name="transport"
        value={form.transport}
        onChange={handleChange}
        className="border rounded-lg px-4 py-2"
      >
        {TRANSPORT_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <textarea
        name="constraints"
        placeholder="Any constraints? (optional)"
        value={form.constraints}
        onChange={handleChange}
        rows={2}
        className="border rounded-lg px-4 py-2 resize-none"
      />
      <button
        type="submit"
        disabled={isLoading}
        className="bg-black text-white rounded-lg py-2 font-medium disabled:opacity-50"
      >
        {isLoading ? "Planning…" : "Plan My Day"}
      </button>
    </form>
  );
}
