import _ from "lodash";
import { ClassicListenersCollector } from "@empirica/core/admin/classic";
export const Empirica = new ClassicListenersCollector();
import { promises as fs } from 'fs';
import { join } from 'path';

const names = [
"Repi",
"Minu",
"Laju",
"Hera",
]; // for the players names to match avatar color

// Blue avatar names and color codes:
const avatarURLs = [
  "/avatars/blue.png",
  "/avatars/red.png",
  "/avatars/yellow.png",
  "/avatars/green.png",
]

const nameColors = [
"#29828D", // Aria
  "#444EA1", // Katherine
  "#57AEC6", // Kayla
  "#5792C8" // Oliver
]

// Get the directory name of the current module

Empirica.onGameStart(async ({ game }) => {
  // Set treatment variables for client-side access
  const treatment = game.get("treatment");
  game.set("showNegativeFeedback", treatment.showNegativeFeedback);
  game.set("contextSize", treatment.contextSize);
  game.set("contextStructure", treatment.contextStructure)
  game.set("maxTimeout", treatment.maxTimeout)
  game.set("numRoundsInactive", 0);
  game.set("endedInactive", false);
  // rotations
  const possibleRotations = [0, 90, 180, 270]

const gameRotation = _.sample(possibleRotations)
console.log("Game rotation set to:", gameRotation, "degrees for game", game.id);
game.set("rotation", gameRotation);

  let topTangrams, bottomTangrams, targetTangrams;
  try {
    const jsonTangramPath = game.get("contextStructure") == "noncomp"
      ? "noncomp_sets.json"  // Just the filename since it's in the same directory
      : "comp_sets.json";
        
    const jsonContent = await fs.readFile(jsonTangramPath, 'utf8');
      const allSets = JSON.parse(jsonContent);
      const selectedSet = _.sample(allSets);
      
      topTangrams = selectedSet.top_tangrams;
      bottomTangrams = selectedSet.bottom_tangrams;
     targetTangrams = [];
  
      if (game.get("contextStructure") == "noncomp") {
        for (let i = 0; i < topTangrams.length; i++){
          targetTangrams.push([topTangrams[i], bottomTangrams[i]])
        }
      } else {
        for (let i = 0; i < game.get("contextSize"); i++) {
          for (let j = 0; j < game.get("contextSize"); j++) {  // Fixed j declaration
            targetTangrams.push([topTangrams[i], bottomTangrams[j]])
          }
        }}
        game.set("topTangrams", topTangrams)
        game.set("bottomTangrams", bottomTangrams)
        game.set('targets', targetTangrams)

      // Rest of your code remains the same...
    } catch (error) {
      console.error("Error loading tangram sets:", error);
      throw error;
    }
  // initialize players
  game.players.forEach((player, i) => {
    const otherPlayer = game.players.filter((p) => p.id != player.id);
    //player.set("tangramURLs", _.shuffle(game.get('context')));
    player.set("avatar",`https://api.dicebear.com/8.x/rings/svg?seed=${names[i]}`); //chat
    player.set("src", avatarURLs[i]);
    player.set('name', names[i]);
    player.set("nameColor", nameColors[i]);
    player.set("partner", otherPlayer[0].id)
    player.set("role", i == 0 ? 'director' : 'matcher'); //first player is always speaker (if overfill there may be multiple listeners??)
    player.set("bonus", 0);
    player.set("score", 0);
  });

  const targets = game.get('targets')
  const reps = treatment.numRepetitionsWithPartner;
  const numTargets = targets.length;
  const numPartners = game.players.length - 1;
  const info = {
    numTrialsPerBlock : numTargets,
    numRepsPerPartner : reps,
    numTrialsPerPartner: reps * numTargets
  };

  // use this to play the sound on the UI when the game starts
  game.set("justStarted", true);

  // Loop through repetition blocks
  _.times(reps, repNum => {
    const block = _.shuffle(targets)

    // Loop through targets in block
    _.times(numTargets, targetNum => {
      const target = block[targetNum]
      let tangrams;

      if (game.get("contextStructure") == "noncomp") {
        const non_target_alternatives = targets.filter(x => x.every(function(element, index) {return element !== target[index];}))
        const contrast_tangrams = _.sampleSize(non_target_alternatives, game.get("contextSize")-1)
        //console.log(non_target_alternatives)
        tangrams = [target].concat(contrast_tangrams)
        tangrams = _.shuffle(tangrams)
      } else if (game.get("contextStructure") == "comp-within") {
        // select one non-target top to serve as the top shape and one non-target bottom to serve as the bottom shape
        const top_alternative = _.sample(topTangrams.filter(x => x != target[0]));
        const bottom_alternative = _.sample(bottomTangrams.filter(x => x != target[1]));
        const contrast_tangrams = [[target[0], bottom_alternative], [top_alternative, target[1]], [top_alternative, bottom_alternative]];
        //console.log(non_target_alternatives)
        tangrams = [target].concat(contrast_tangrams)
        tangrams = _.shuffle(tangrams)
      } else {
        let top_alternatives = _.shuffle(topTangrams.filter(x => x != target[0]));
        let bottom_alternatives = _.shuffle(bottomTangrams.filter(x => x != target[1]));
        const contrast_tangrams = [[top_alternatives[0], bottom_alternatives[0]], [top_alternatives[1], bottom_alternatives[1]], [top_alternatives[2], bottom_alternatives[2]]];
        //console.log(non_target_alternatives)
        tangrams = [target].concat(contrast_tangrams)
        tangrams = _.shuffle(tangrams)
      }
      //console.log(tangrams)

      const tangramURLs = []
      for (let i = 0; i < tangrams.length; i ++ ){
        tangramURLs.push("/tangrams/" + tangrams[i][0] + "_" + tangrams[i][1] + '.png')
      }
      const targetURL = "/tangrams/" + target[0] + "_" + target[1] + '.png'

      const round = game.addRound({
        target: targetURL,
        numTrials: (reps * numTargets) + 1,
        targetNum: targetNum + 1,
        trialNum : repNum * numTargets + targetNum,
        repNum : repNum,
        reps: reps,
        tangramURLs: tangramURLs
      });

      round.addStage({
        name: "selection",
        duration: treatment.selectionDuration
      });
      round.addStage({
        name: "feedback",
        duration: treatment.feedbackDuration
      });
    });
  });
  console.log(game.get("contextStructure")," ", game.id, " started")
});

Empirica.onRoundStart(({ round }) => {

  const players = round.currentGame.players;
  round.set('selection', '')
  round.set("justStarted", true);

  const chat = round.get("chat") ?? [];

  players.forEach((player, i) => {
    //player.set('clicked', '');
    // swap player roles
    player.set("role", player.get('role') == 'director' ? 'matcher' : 'director');
    round.set(player.get('role'), player.id);
  });
});

Empirica.onStageStart(({ stage }) => {
});

Empirica.onStageEnded(({ stage }) => {});

Empirica.onRoundEnded(({ round }) => {
  const players = round.currentGame.players;
  const game = round.currentGame;
  const target = round.get('target');
  const selectedAnswer = round.get('selection')

  // Update player scores
  players.forEach(player => {
    const currScore = player.get("bonus") || 0;
    const scoreIncrement = selectedAnswer === target ? .03 : 0;
    player.set("bonus", scoreIncrement + currScore);
    player.set("score", scoreIncrement + currScore);
  })
  const currentSelection = round.get('selection');
  const currentInactive = game.get("numRoundsInactive");

  console.log(`Game ${game.id} - ${round.get("trialNum")}/${round.get("numTrials")}`);
  console.log(`- target: "${target}", selection: "${currentSelection}", inactive count: ${game.get("numRoundsInactive")}`);
  
  if (currentSelection === '') {
    // No selection - increment inactivity counter
    const currNumInactive = game.get("numRoundsInactive");
    const newInactiveCount = currNumInactive + 1;
    game.set("numRoundsInactive", newInactiveCount);
  
    // Check if exceeded timeout
    if (newInactiveCount >= game.get("maxTimeout")) {
      if (!game.get("ended")) {
        console.log(`Marking Game ${game.id} as ended due to timeout`);
        game.set("endedInactive", true);
        game.end("ended", "timeOut");
      }
    }
  } else {
    // Only log if we're resetting from an inactive state
    if (currentInactive > 0) {
      console.log(`Reset inactivity counter for game ${game.id} - they responded after ${currentInactive} inactive rounds`);
    } 
    game.set("numRoundsInactive", 0);
  }

  // Save outcomes as property of round for later export/analysis
  round.set('response', round.get('selection'));
  round.set('correct', target === round.get('selection'));
});

Empirica.onGameEnded(({ game }) => {});