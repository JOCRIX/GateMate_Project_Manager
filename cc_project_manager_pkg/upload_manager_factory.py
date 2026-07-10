"""Factory for creating the appropriate FPGA programming manager for a board."""
from typing import Union

from .openfpgaloader_manager import OpenFPGALoaderManager
from .zi_fpga_loader_manager import ZiFPGALoaderManager


def get_board_programming_tool(board_identifier: str) -> str:
    """Return the programming tool id for a board ('openfpgaloader' or 'zi_fpga_loader')."""
    try:
        from .boards_manager import BoardsManager

        board = BoardsManager().get_board_details(board_identifier)
        if board:
            return board.get("programming_tool", "openfpgaloader")
    except Exception:
        pass
    return "openfpgaloader"


def create_upload_manager(
    board_identifier: str,
) -> Union[OpenFPGALoaderManager, ZiFPGALoaderManager]:
    """Create the upload manager appropriate for the selected board."""
    tool = get_board_programming_tool(board_identifier)
    if tool == "zi_fpga_loader":
        return ZiFPGALoaderManager(board_identifier=board_identifier)
    return OpenFPGALoaderManager(board_identifier=board_identifier)
