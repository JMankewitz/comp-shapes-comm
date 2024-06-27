import _ from "lodash";
import { ClassicListenersCollector } from "@empirica/core/admin/classic";
export const Empirica = new ClassicListenersCollector();



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


Empirica.onGameStart(({ game }) => {
  // Set treatment variables for client-side access
  const treatment = game.get("treatment");
  game.set("showNegativeFeedback", treatment.showNegativeFeedback);
  game.set("contextSize", treatment.contextSize);
  game.set("contextStructure", treatment.contextStructure)

  let topTangrams = []
  let bottomTangrams = []

  const targetTangrams = []
  if (game.get("contextStructure") == "noncomp") {
    topTangrams = _.range(16);
    bottomTangrams = _.range(start = 16, end = 32);
    for (let i = 0; i < 16; i++){
      targetTangrams.push([topTangrams[i], bottomTangrams[i]])
    }

  } else {
    topTangrams = _.range(4);
    bottomTangrams = _.range(start = 16, end = 20);
    
    for (let i = 0; i < game.get("contextSize"); i++){
      for (j = 0; j < game.get("contextSize"); j++){
        targetTangrams.push([topTangrams[i], bottomTangrams[j]])
      }
    }
  }
  
  game.set("topTangrams", topTangrams)
  game.set("bottomTangrams", bottomTangrams)

  console.log(topTangrams)
  console.log(bottomTangrams)
  console.log(targetTangrams)
  game.set('targets', targetTangrams)

  // initialize players
  game.players.forEach((player, i) => {
    const otherPlayer = game.players.filter((p) => p.id != player.id);
    //player.set("tangramURLs", _.shuffle(game.get('context')));
    player.set("avatar",`https://api.dicebear.com/8.x/rings/svg?seed=${names[i]}`); //chat
    player.set("src", avatarURLs[i]);
    player.set('name', names[i]);
    player.set("nameColor", nameColors[i]);
    player.set("partner", otherPlayer[0].id)
    player.set("role", i == 0 ? 'speaker' : 'listener'); //first player is always speaker (if overfill there may be multiple listeners??)
    player.set("bonus", 0);
    player.set("score", 0)
    console.log('resetting interval')
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
      console.log(tangrams)

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
});

Empirica.onRoundStart(({ round }) => {

  const players = round.currentGame.players;

  const chat = round.get("chat") ?? [];
  players.forEach((player, i) => {
    player.set('clicked', '');
    // swap player roles
    player.set("role", player.get('role') == 'speaker' ? 'listener' : 'speaker');
  });
});

Empirica.onStageStart(({ stage }) => {});

Empirica.onStageEnded(({ stage }) => {});

Empirica.onRoundEnded(({ round }) => {
  const players = round.currentGame.players;
  const target = round.get('target');

  // Update player scores
  players.forEach(player => {
    const selectedAnswer = player.get("clicked");
    const currScore = player.get("bonus") || 0;
    const correctAnswer = target
    const scoreIncrement = selectedAnswer == correctAnswer ? .03 : 0;

    player.set("bonus", scoreIncrement + currScore);
    player.set("score", scoreIncrement + currScore)
  });

  // Save outcomes as property of round for later export/analysis
  const player1 = players[0]
  round.set('response', player1.get('clicked'));
  round.set('correct', target == player1.get('clicked'));

  // check if they've not responded for two consecutive rounds
  players.forEach((p) => {
    const inactive = player.get("numRoundsInactive")
    if(inactive > 2) {
      player.set("ended", "exitSurvey")
    }
  })


});

Empirica.onGameEnded(({ game }) => {});

