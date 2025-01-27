# Pulls the raw data output from empirica and tidies it

library(tidyverse)
library(here)
library(jsonlite)

target_experiment_name <- "run_v3/18-1"

target_demo_folder <- here("data/raw_data", target_experiment_name)

processed_data_folder <- here("data/processed_data", target_experiment_name)

d_game_raw <- read_csv(here(target_demo_folder, "game.csv"))
d_batch_raw <- read_csv(here(target_demo_folder, "batch.csv"))
d_player_raw <- read_csv(here(target_demo_folder, "player.csv"))
d_round_raw <- read_csv(here(target_demo_folder, "round.csv"))
d_stage_raw <- read_csv(here(target_demo_folder, "stage.csv"))

# extract game info (game ID, condition, etc)

d_game <- d_game_raw |> 
  select(gameID = id, actualPlayerCount, batchID, contextSize, contextStructure, status, targets, rotation)

d_players <- d_player_raw |> 
  mutate(URLParams = map(urlParams, ~ possibly(function(x) {
    if (is.na(x)) return(data.frame())
    fromJSON(x) %>% as.data.frame()
  }, otherwise = data.frame())(.)
  )) |>
  unnest(URLParams) |>
  select(playerID = id, prolificID = participantKey,bonus, exitStepDone, exitSurvey, gameID) 

d_players_exit <- d_players |> 
  select(playerID, exitSurvey) |> filter(!is.na(exitSurvey)) |> 
  mutate(exitSurvey = map(exitSurvey, ~ fromJSON(.) %>% as.data.frame())) %>% 
  unnest(exitSurvey)

d_players <- d_players |> select(-exitSurvey) |> left_join(d_players_exit)

d_round <- d_round_raw |>  select(roundID = id, correct, gameID, index, numTrials, repNum, 
                                  response, target, targetNum, trialNum, tangramURLs)

d_chat <- d_round_raw |>  select(roundID = id, chat, director) |>  filter(!is.na(chat)) |> 
  mutate(chat = map(chat, ~ fromJSON(.) %>% as.data.frame())) %>% 
  unnest(chat) |> 
  unnest(sender) |> 
  mutate(director_msg = (id == director),
         chit_chat = FALSE) %>% 
  select(roundID, text, playerID = id, director_msg, chit_chat)



# write preprocessed CSVs

d_game |> write_csv(here(processed_data_folder, "games.csv"))
d_round |> write_csv(here(processed_data_folder, "rounds.csv"))
d_chat |> write_csv(here(processed_data_folder, "chats.csv"))
d_players |> write_csv(here(processed_data_folder, "players.csv"))
