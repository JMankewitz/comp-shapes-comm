import React, { useState } from "react";
import { Button } from "../components/Button";
  // Assuming you have access to the same Button component

export function MyPlayerForm({ onPlayerID, connecting }) {
  const [playerID, setPlayerID] = useState("");

  const handleSubmit = (evt) => {
    evt.preventDefault();
    if (!playerID || playerID.trim() === "") {
      return;
    }
    onPlayerID(playerID);
  };

  return (
    <div className="h-screen flex flex-col items-center justify-center bg-gray-50">
      <div className="max-w-md w-full px-4 py-8">
        <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
          Please Enter your Prolific ID
        </h2>
        
        <form 
          action="#" 
          method="POST" 
          onSubmit={handleSubmit}
          className="mt-8 space-y-6"
        >
          <fieldset 
            disabled={connecting}
            className="space-y-4"
          >
            <div>
              <label 
                htmlFor="playerID" 
                className="block text-sm font-medium text-gray-700"
              >
                Prolific ID
              </label>
              <div className="mt-1">
                <input
                  id="playerID"
                  name="playerID"
                  type="text"
                  autoComplete="off"
                  required
                  autoFocus
                  value={playerID}
                  onChange={(e) => setPlayerID(e.target.value)}
                  className="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-empirica-500 focus:border-empirica-500 sm:text-sm"
                />
              </div>
            </div>

            <div className="flex justify-center">
              <Button 
                type="submit"
                handleClick={() => {}}  // Submit is handled by form onSubmit
                primary
                className="w-32"
              >
                {connecting ? "Loading..." : "Enter"}
              </Button>
            </div>
          </fieldset>
        </form>

        {connecting && (
          <div className="mt-4 text-center text-sm text-gray-600">
            Connecting...
          </div>
        )}
      </div>
    </div>
  );
}