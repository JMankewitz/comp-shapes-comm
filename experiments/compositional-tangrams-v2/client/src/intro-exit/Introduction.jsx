import React from "react";
import { Button } from "../components/Button";
import { InstructionsBody } from "./InstructionsBody";

export function Introduction({ next }) {
  return (
    <div className="mt-3 sm:mt-5 p-20">
      <h3 className="text-lg leading-6 font-medium text-gray-1000">
        Task Instructions
      </h3>
      <h2>Matching Game  </h2>
      <InstructionsBody />

      <Button handleClick={next} autoFocus>
        <p>Next</p>
      </Button>
    </div>
  );
}
