from dataclasses import dataclass
from typing import Optional


@dataclass
class WNBAGame:
    game_id: str
    date: str
    season: int

    player_id: str
    player: str

    team: str
    opponent: str
    home_away: str

    minutes: float
    starter: bool
    days_rest: Optional[int]

    points: int
    rebounds: int
    assists: int
    three_pm: int

    steals: int
    blocks: int
    turnovers: int

    fg_made: int
    fg_attempts: int

    three_pa: int

    ft_made: int
    ft_attempts: int

    offensive_rebounds: int
    defensive_rebounds: int

    personal_fouls: int
    plus_minus: float

    @property
    def pra(self):
        return self.points + self.rebounds + self.assists

    @property
    def ra(self):
        return self.rebounds + self.assists

    @property
    def pa(self):
        return self.points + self.assists

    @property
    def pr(self):
        return self.points + self.rebounds


def print_game(game: WNBAGame):

    print("=" * 50)

    print(game.player)
    print(game.team, "vs", game.opponent)

    print("PTS:", game.points)
    print("REB:", game.rebounds)
    print("AST:", game.assists)
    print("3PM:", game.three_pm)

    print()

    print("PRA:", game.pra)
    print("RA:", game.ra)
    print("PA:", game.pa)
    print("PR:", game.pr)

    print("=" * 50)


if __name__ == "__main__":

    # Temporary test game.
    # This will be replaced by real imported data.

    test_game = WNBAGame(

        game_id="TEST001",
        date="2026-06-01",
        season=2026,

        player_id="123",
        player="Test Player",

        team="IND",
        opponent="NYL",
        home_away="HOME",

        minutes=34.5,
        starter=True,
        days_rest=2,

        points=22,
        rebounds=9,
        assists=6,
        three_pm=2,

        steals=1,
        blocks=2,
        turnovers=3,

        fg_made=8,
        fg_attempts=17,

        three_pa=5,

        ft_made=4,
        ft_attempts=5,

        offensive_rebounds=2,
        defensive_rebounds=7,

        personal_fouls=2,
        plus_minus=8
    )

    print_game(test_game)
