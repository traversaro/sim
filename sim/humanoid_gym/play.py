"""Script to replay a trained policy in the environment."""

import argparse
import os
from datetime import datetime

import cv2
import numpy as np
from isaacgym import gymapi
from tqdm import tqdm

from sim.env import run_dir
from sim.humanoid_gym.envs import *  # noqa: F403


def play(args: argparse.Namespace) -> None:
    env_cfg, train_cfg = task_registry.get_cfgs(name=args.task)
    # override some parameters for testing
    env_cfg.env.num_envs = min(env_cfg.env.num_envs, 1)
    env_cfg.sim.max_gpu_contact_pairs = 2**10
    # env_cfg.terrain.mesh_type = 'trimesh'
    env_cfg.terrain.mesh_type = "plane"
    env_cfg.terrain.num_rows = 5
    env_cfg.terrain.num_cols = 5
    env_cfg.terrain.curriculum = False
    env_cfg.terrain.max_init_terrain_level = 5
    env_cfg.noise.add_noise = True
    env_cfg.domain_rand.push_robots = False
    env_cfg.domain_rand.joint_angle_noise = 0.0
    env_cfg.noise.curriculum = False
    env_cfg.noise.noise_level = 0.5

    train_cfg.seed = 123145
    print("train_cfg.runner_class_name:", train_cfg.runner_class_name)

    # prepare environment
    env, _ = task_registry.make_env(name=args.task, args=args, env_cfg=env_cfg)
    env.set_camera(env_cfg.viewer.pos, env_cfg.viewer.lookat)

    obs = env.get_observations()

    # load policy
    train_cfg.runner.resume = True
    ppo_runner, train_cfg = task_registry.make_alg_runner(env=env, name=args.task, args=args, train_cfg=train_cfg)
    policy = ppo_runner.get_inference_policy(device=env.device)

    logger = Logger(env.dt)
    robot_index = 0  # which robot is used for logging
    joint_index = 1  # which joint is used for logging
    stop_state_log = 1200  # number of steps before plotting states

    if RENDER:
        camera_properties = gymapi.CameraProperties()
        camera_properties.width = 1920
        camera_properties.height = 1080
        h1 = env.gym.create_camera_sensor(env.envs[0], camera_properties)
        camera_offset = gymapi.Vec3(3, -3, 1)
        camera_rotation = gymapi.Quat.from_axis_angle(gymapi.Vec3(-0.3, 0.2, 1), np.deg2rad(135))
        actor_handle = env.gym.get_actor_handle(env.envs[0], 0)
        body_handle = env.gym.get_actor_rigid_body_handle(env.envs[0], actor_handle, 0)
        print(body_handle)
        print(actor_handle)
        env.gym.attach_camera_to_body(
            h1, env.envs[0], body_handle, gymapi.Transform(camera_offset, camera_rotation), gymapi.FOLLOW_POSITION
        )

        fourcc = cv2.VideoWriter_fourcc(*"MJPG")

        # Creates a directory to store videos.
        video_dir = run_dir() / "videos"
        experiment_dir = video_dir / train_cfg.runner.experiment_name
        experiment_dir.mkdir(parents=True, exist_ok=True)

        dir = os.path.join(experiment_dir, datetime.now().strftime("%b%d_%H-%M-%S") + args.run_name + ".mp4")
        if not os.path.exists(video_dir):
            os.mkdir(video_dir)
        if not os.path.exists(experiment_dir):
            os.mkdir(experiment_dir)
        video = cv2.VideoWriter(dir, fourcc, 50.0, (1920, 1080))

    for _ in tqdm(range(stop_state_log)):
        actions = policy(obs.detach())

        if FIX_COMMAND:
            env.commands[:, 0] = 0.0
            env.commands[:, 1] = -0.5  # negative left, positive right
            env.commands[:, 2] = 0.0
            env.commands[:, 3] = 0.0

        obs, critic_obs, rews, dones, infos = env.step(actions.detach())

        if RENDER:
            env.gym.fetch_results(env.sim, True)
            env.gym.step_graphics(env.sim)
            env.gym.render_all_camera_sensors(env.sim)
            img = env.gym.get_camera_image(env.sim, env.envs[0], h1, gymapi.IMAGE_COLOR)
            img = np.reshape(img, (1080, 1920, 4))
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)

            video.write(img[..., :3])  # Write only the RGB channels

        logger.log_states(
            {
                "dof_pos_target": actions[robot_index, joint_index].item() * env.cfg.control.action_scale,
                "dof_pos": env.dof_pos[robot_index, joint_index].item(),
                "dof_vel": env.dof_vel[robot_index, joint_index].item(),
                "dof_torque": env.torques[robot_index, joint_index].item(),
                "command_x": env.commands[robot_index, 0].item(),
                "command_y": env.commands[robot_index, 1].item(),
                "command_yaw": env.commands[robot_index, 2].item(),
                "base_vel_x": env.base_lin_vel[robot_index, 0].item(),
                "base_vel_y": env.base_lin_vel[robot_index, 1].item(),
                "base_vel_z": env.base_lin_vel[robot_index, 2].item(),
                "base_vel_yaw": env.base_ang_vel[robot_index, 2].item(),
                "contact_forces_z": env.contact_forces[robot_index, env.feet_indices, 2].cpu().numpy(),
            }
        )
        # ====================== Log states ======================
        if infos["episode"]:
            num_episodes = env.reset_buf.sum().item()
            if num_episodes > 0:
                logger.log_rewards(infos["episode"], num_episodes)

    logger.print_rewards()
    logger.plot_states()

    if RENDER:
        video.release()


# Puts this import down here so that the environments are registered
# before we try to use them.
from humanoid.utils import Logger, get_args, task_registry  # noqa: E402

if __name__ == "__main__":
    RENDER = True
    FIX_COMMAND = True

    play(get_args())
