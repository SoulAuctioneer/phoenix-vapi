import asyncio
import logging
from config import PLATFORM

logger = logging.getLogger(__name__)

async def _run_shell_command(command: str):
    """Executes a shell command and logs its output."""
    if PLATFORM != "raspberry-pi":
        logger.debug(f"Skipping shell command on non-Pi platform: '{command}'")
        return True, "", ""

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        stdout_str = stdout.decode().strip()
        stderr_str = stderr.decode().strip()

        if process.returncode == 0:
            logger.info(f"Successfully executed: '{command}'. stdout: {stdout_str}")
            return True, stdout_str, stderr_str
        else:
            logger.error(f"Error executing: '{command}'. Return code: {process.returncode}")
            if stdout_str:
                logger.error(f"STDOUT: {stdout_str}")
            if stderr_str:
                logger.error(f"STDERR: {stderr_str}")
            return False, stdout_str, stderr_str
    except FileNotFoundError:
        logger.error(f"Command not found: '{command.split()[0]}'. Is it installed and in PATH?")
        return False, "", "Command not found"
    except Exception as e:
        logger.error(f"Exception executing command '{command}': {e}", exc_info=True)
        return False, "", str(e)

async def set_cpu_governor(governor: str):
    """
    Sets the CPU governor on a Raspberry Pi.
    Requires `cpufrequtils` to be installed and passwordless sudo for `cpufreq-set`.
    
    Args:
        governor: The desired governor (e.g., 'powersave', 'ondemand', 'performance').
    """
    if governor not in ['powersave', 'ondemand', 'performance']:
        logger.warning(f"Invalid CPU governor specified: {governor}")
        return
    
    # NOTE: This requires passwordless sudo for the `cpufreq-set` command.
    # Add to /etc/sudoers.d/phoenix:
    # <user> ALL=(ALL) NOPASSWD: /usr/bin/cpufreq-set
    command = f"sudo cpufreq-set -g {governor}"
    await _run_shell_command(command)

async def set_bluetooth_enabled(enabled: bool):
    """
    Enables or disables the Bluetooth adapter on a Raspberry Pi.
    Requires passwordless sudo for the `rfkill` command.
    """
    action = "unblock" if enabled else "block"
    
    # NOTE: This requires passwordless sudo for the `rfkill` command.
    # Add to /etc/sudoers.d/phoenix:
    # <user> ALL=(ALL) NOPASSWD: /usr/sbin/rfkill
    command = f"sudo rfkill {action} bluetooth"
    await _run_shell_command(command)

async def shutdown_pi():
    """
    Shuts down the Raspberry Pi gracefully.
    Requires passwordless sudo for the `shutdown` command.
    """
    logger.info("Shutting down the system now.")
    # NOTE: This requires passwordless sudo for the `shutdown` command.
    # Add to /etc/sudoers.d/phoenix:
    # <user> ALL=(ALL) NOPASSWD: /sbin/shutdown
    command = "sudo shutdown -h now"
    await _run_shell_command(command)

async def reboot_pi():
    """
    Reboots the Raspberry Pi gracefully.
    Requires passwordless sudo for the `shutdown` command.
    """
    logger.info("Rebooting the system now.")
    # NOTE: This requires passwordless sudo for the `shutdown` command.
    # Add to /etc/sudoers.d/phoenix:
    # <user> ALL=(ALL) NOPASSWD: /sbin/shutdown
    command = "sudo shutdown -r now"
    await _run_shell_command(command) 