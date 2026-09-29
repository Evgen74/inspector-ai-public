import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import type { NestFastifyApplication } from '@nestjs/platform-fastify';
import { Logger } from 'nestjs-pino';
import { AppModule } from './app.module';
import { configureApp, createFastifyAdapter } from './bootstrap';
import { ConfigError, loadConfig } from './config/config';

const EX_CONFIG = 78;

async function main(): Promise<void> {
  let config;
  try {
    config = loadConfig();
  } catch (err) {
    console.error(err instanceof ConfigError ? err.message : String(err));
    process.exit(EX_CONFIG);
  }
  const app = await NestFactory.create<NestFastifyApplication>(AppModule.forRoot(config), createFastifyAdapter(), {
    bufferLogs: true,
  });
  await configureApp(app);
  await app.listen({ port: config.port, host: config.host });
  app
    .get(Logger)
    .log(
      `API «Инспектор ИИ» слушает http://${config.host}:${config.port}/api/v1 (runs: ${config.runsRoot}, env: ${config.appEnv})`,
      'Bootstrap',
    );
}

void main();
