import React, { useState } from "react";

export function MyPlayerForm({ onPlayerID, connecting }) {
  // For the text input field.
  const [playerID, setPlayerID] = useState("");

  // Handling the player submitting their ID.
  const handleSubmit = (evt) => {
    evt.preventDefault();
    if (!playerID || playerID.trim() === "") {
      return;
    }

    onPlayerID(playerID);
  };

  return (
    <div>
      <div>Confirm your Prolific ID</div>

      <form action="#" method="POST" onSubmit={handleSubmit}>
        <fieldset disabled={connecting}>
          <label htmlFor="playerID">Identifier</label>
          <input
            id="playerID"
            name="playerID"
            type="text"
            autoComplete="off"
            required
            autoFocus
            value={playerID}
            onChange={(e) => setPlayerID(e.target.value)}
          />

          <button type="submit">Enter</button>
        </fieldset>
      </form>
    </div>
  );
}