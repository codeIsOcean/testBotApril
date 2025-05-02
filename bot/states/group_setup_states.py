from aiogram.fsm.state import State, StatesGroup


class SetupStates(StatesGroup):
    waiting_for_setup = State()  # состояние: ждем какую группу настраивать
