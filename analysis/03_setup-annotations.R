library(tidyverse)
library(here)
final_game_set <- "run_v3"

target_experiment_names <- list.files(here("data", "processed_data", final_game_set))

old_conditions <- c('noncomp','comp-within','comp-between')
new_conditions_long <- c('No Competitor','Within Trial','Across Trial')
new_conditions_short <- c('No Comp','Comp Within','Comp Between')

game_blacklist <- c("01JGZ1J4WKTCRGQS8R8214JJH2",#AI response
                    "01JGMPEGCD0EX4TXSSNEY3A670" #AI response
)

load_data <- function(data_name, study_list) {
  source_files <- list.files(path = here("data", "processed_data", final_game_set),
                             recursive = TRUE,
                             pattern = paste0(data_name, ".csv$"),
                             full.names = TRUE)
  
  mod_read_csv <- function(data_file, data_name){
    read.csv(data_file)
  }
  
  data_files <- source_files[Reduce("|", lapply(study_list, function(x) grepl(x, source_files)))]
  do.call(bind_rows, lapply(data_files, mod_read_csv))
}

d_game <- load_data("games", target_experiment_names)
d_round <- load_data("rounds", target_experiment_names)
d_chat <- load_data("chats", target_experiment_names)
d_players <- load_data("players", target_experiment_names)

d_game$contextStructure_f <- factor(d_game$contextStructure, levels=old_conditions,
                                    labels=new_conditions_long)

d_game <- d_game %>% mutate(contextStructure_f = relevel(contextStructure_f, ref = 'No Competitor'))


game_stats <- d_round |> 
  left_join(d_game) |> 
  group_by(gameID, contextStructure, contextStructure_f) |> 
  summarize(n_correct = sum(correct, na.rm = T),
            n_responses = sum(!is.na(response))) %>% 
  filter(n_responses > 0) %>% 
  mutate(non_response_rate = n_responses < 32,
         inaccuracy = n_correct/n_responses < .75,
         blacklist = gameID %in% game_blacklist,
         kept_game = ! non_response_rate & ! inaccuracy & ! blacklist)

non_response <- game_stats %>% 
  group_by(non_response_rate, inaccuracy, blacklist, kept_game) |> 
  summarise(n_games = n_distinct(gameID)) %>% 
  filter(non_response_rate)

inaccuracy <- game_stats %>% 
  group_by(non_response_rate, inaccuracy, blacklist, kept_game) |> 
  summarise(n_games = n_distinct(gameID)) %>% 
  filter(!non_response_rate, inaccuracy)

blacklist <- game_stats %>% 
  group_by(non_response_rate, inaccuracy, blacklist, kept_game) |> 
  summarise(n_games = n_distinct(gameID)) %>% 
  filter(blacklist)

final_n <- game_stats %>% 
  group_by(contextStructure, contextStructure_f, kept_game) |> 
  summarise(n_games = n_distinct(gameID)) %>% 
  pivot_wider(names_from = kept_game, values_from=n_games) %>% 
  rename("excluded" = `FALSE`, "included" = `TRUE`) %>% 
  mutate(prop_excluded = excluded/(excluded+included))
final_n


d_game_f <- d_game %>% left_join(game_stats %>% select(gameID, kept_game)) %>% filter(kept_game)
d_round_f <- d_round %>% left_join(game_stats %>% select(gameID, kept_game)) %>% filter(kept_game)
d_chat_f <- d_chat %>% left_join(d_round_f %>% select(roundID, kept_game, gameID)) %>% filter(kept_game)
d_players_f <- d_players %>% left_join(game_stats %>% select(gameID, kept_game)) %>% filter(kept_game)
d_chat_similarity_f <- d_chat_similarity %>% left_join(game_stats %>% select(gameID, kept_game)) %>% filter(kept_game)

d_chat_cleaned <- d_chat_f %>% 
  full_join(d_round_f) |> 
  left_join(d_game_f) |> 
  filter(kept_game) %>% 
  filter(director_msg) %>% 
  filter(!chit_chat | is.na(chit_chat)) %>% #filter out chit-chat
  mutate(text = gsub('[[:punct:] ]+',' ',text), #stripping some punctuation
         text = str_squish(text),
         utt_length_chars = str_length(text), 
         utt_length_words = str_count(text, "\\W+") + 1)

d_chat_word_counts <-d_chat_cleaned %>% 
  group_by(gameID, index, repNum, playerID, target, contextStructure_f) %>%
  summarize(text = paste0(text, collapse = ', '),
            total_num_words = sum(utt_length_words),
            total_num_chars = sum(utt_length_chars))


batch_num = 8

d_chat_round <- d_round_f |> 
  left_join(d_chat_word_counts) |> 
  left_join(d_game_f |> 
              group_by(contextStructure) |> 
              slice_sample(n=1) |> 
              mutate(sampled_game = TRUE)) |> 
  filter(sampled_game, repNum == 3) |> 
  write_csv(here(paste0("data/processed_data/chats_rounds_", batch_num, ".csv")))


